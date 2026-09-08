import argparse
import http.server
import importlib.util
import json
import os
import re
import socketserver
from typing import Any

# --- UNIVERSAL CXAS SLOT-FILLING UI SERVER ---

DEFAULT_PORT = 8085
DEFAULT_DIRECTORY = "../schwab_cashiering"
DEFAULT_AGENT = "Cashiering"
HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webwidget-deploy.html")


class MockFunctionCall:
    def __init__(self, name, args):
        self.name = name
        self.args = args


class Part:
    def __init__(self, text=None, function_call=None, custom_payload=None, agent_transfer=None):
        self.text = text
        self.function_call = function_call
        self.custom_payload = custom_payload
        self.agent_transfer = agent_transfer

    @classmethod
    def from_text(cls, text):
        return cls(text=text)

    @classmethod
    def from_json(cls, json_str):
        try:
            data = json.loads(json_str)
            return cls(custom_payload=data)
        except Exception:
            return cls(text=json_str)

    @classmethod
    def from_function_call(cls, name, args):
        return cls(function_call=MockFunctionCall(name, args))

    @classmethod
    def from_agent_transfer(cls, target_agent):
        return cls(agent_transfer=target_agent)


class Content:
    def __init__(self, parts, role="model"):
        self.parts = parts
        self.role = role


class LlmResponse:
    def __init__(self, content):
        self.content = content

    @classmethod
    def from_parts(cls, parts):
        return cls(Content(parts))


class LlmRequestConfig:
    def __init__(self, system_instruction=""):
        self.system_instruction = system_instruction
        self.hidden_tools = []

    def hide_tool(self, name):
        if name not in self.hidden_tools:
            self.hidden_tools.append(name)


class LlmRequest:
    def __init__(self, contents, system_instruction=""):
        self.contents = contents
        self.config = LlmRequestConfig(system_instruction)


class MockUserContent:
    def __init__(self, text):
        self.parts = [Part(text=text)] if text else []


class CallbackContext:
    def __init__(self, state, last_user_text="", events=None):
        self.state = state
        self.user_content = MockUserContent(last_user_text)
        self.events = events or []
        self.variables = state

    def get_last_user_input(self):
        return self.user_content.parts


class MockEvent:
    def __init__(self, is_user_flag=True):
        self._is_user = is_user_flag

    def is_user(self):
        return self._is_user


class MockResult:
    def __init__(self, r):
        self.r = r

    def json(self):
        return self.r


class MockTools:
    def __init__(self, project_root):
        self.project_root = project_root

    def __getattr__(self, name):
        tool_dir = os.path.join(self.project_root, "tools", name)
        if not os.path.isdir(tool_dir):
            def generic_mock(*args, **kwargs):
                return MockResult({"success": True})
            return generic_mock

        py_path = os.path.join(tool_dir, "python_function", "python_code.py")
        if not os.path.exists(py_path):
            def generic_mock(*args, **kwargs):
                return MockResult({"success": True})
            return generic_mock

        spec = importlib.util.spec_from_file_location(name, py_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        func = getattr(mod, name)

        def wrapper(*args, **kwargs):
            if args and isinstance(args[0], dict):
                try:
                    res = func(**args[0])
                except TypeError:
                    res = func(args[0])
            else:
                try:
                    res = func(**kwargs)
                except TypeError:
                    res = func(kwargs)
            return MockResult(res)

        return wrapper


# Global session state dictionary keyed by sessionId for multi-user isolation
APP_DIRECTORY = DEFAULT_DIRECTORY
active_agent = DEFAULT_AGENT
SESSIONS = {}


def get_user_session(session_id: str) -> dict:
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {
            "sm": {"filled": {"channel": "MOBILE"}},
            "history": [],
            "hidden_tools": []
        }
    return SESSIONS[session_id]


def discover_agent_dag_slots(app_dir: str, agent_name: str) -> list[dict]:
    """Dynamically discovers and loads all DAG slot definitions from tools/*_dag or tools/dag_config."""
    tools_dir = os.path.join(app_dir, "tools")
    if not os.path.exists(tools_dir):
        return []

    all_slots = []
    seen_names = set()
    mock_tools = MockTools(app_dir)
    for tool_name in sorted(os.listdir(tools_dir)):
        if tool_name.endswith("_dag") or tool_name == "dag_config":
            try:
                tool_fn = getattr(mock_tools, tool_name)
                res = tool_fn({"agent": agent_name}).json()
                if isinstance(res, dict) and "slots" in res:
                    for s in res["slots"]:
                        sname = s.get("name")
                        if sname and sname not in seen_names:
                            seen_names.add(sname)
                            all_slots.append(s)
            except Exception:
                continue
    return all_slots


def auto_introspect_dag_and_extract_slots(user_text: str, state: dict, app_dir: str, agent_name: str) -> list[str]:
    """Universal DAG schema introspector that extracts slot values from natural language turns."""
    sm = state.setdefault("sm", {})
    filled = sm.setdefault("filled", {})
    tl = user_text.lower().strip()

    dag_slots = discover_agent_dag_slots(app_dir, agent_name)
    discovered_slot_names = [s.get("name") for s in dag_slots if s.get("name")]
    tools_helper = MockTools(app_dir)

    for slot in dag_slots:
        slot_name = slot.get("name")
        if not slot_name:
            continue

        # Verify prerequisite slots are filled before attempting extraction
        reqs = slot.get("requires", [])
        if reqs and not all(state.get(r) or sm.get(r) or filled.get(r) for r in reqs):
            continue

        allowed = slot.get("allowed_values", [])
        setter_name = slot.get("setter")

        if allowed:
            # Match against allowed_values declared in the DAG schema
            for val in allowed:
                val_lower = str(val).lower()
                synonyms = [val_lower]
                if val_lower == "rise":
                    synonyms.extend(["rises", "above", "up"])
                elif val_lower == "drop":
                    synonyms.extend(["drops", "below", "down"])
                elif val_lower in ("last", "bid", "ask"):
                    synonyms.append(f"{val_lower} price")

                if any(syn in tl for syn in synonyms):
                    state[slot_name] = val
                    sm[slot_name] = val
                    filled[slot_name] = val
                    break
        elif setter_name:
            # Invoke setter tool if available or extract open-ended symbol/price values
            try:
                setter_fn = getattr(tools_helper, setter_name)
                res = setter_fn(user_text.strip().upper()).json()
                if isinstance(res, dict):
                    val = res.get("value") or res.get(slot_name) or (user_text.strip().upper() if res.get("valid") else None)
                    if val:
                        state[slot_name] = val
                        sm[slot_name] = val
                        filled[slot_name] = val
            except Exception:
                pass

        # Fallback open-ended extraction for symbol / price / amount slots
        if not filled.get(slot_name):
            if "symbol" in slot_name.lower() or "ticker" in slot_name.lower():
                COMPANY_MAP = {"apple": "AAPL", "tesla": "TSLA", "nvidia": "NVDA", "microsoft": "MSFT", "google": "GOOG", "amazon": "AMZN", "schwab": "SCHW"}
                for comp, sym in COMPANY_MAP.items():
                    if comp in tl:
                        state[slot_name] = sym
                        sm[slot_name] = sym
                        filled[slot_name] = sym
                        break
                if not filled.get(slot_name):
                    for word in user_text.split():
                        clean = word.strip(",.!?\"'$").upper()
                        if clean.isalpha() and 1 <= len(clean) <= 5 and clean not in {"SET", "ALERT", "PRICE", "FOR", "LAST", "BID", "ASK", "RISE", "DROP", "YES", "NO"}:
                            state[slot_name] = clean
                            sm[slot_name] = clean
                            filled[slot_name] = clean
                            break
            elif "price" in slot_name.lower() or "amount" in slot_name.lower():
                price_match = re.search(r"\b(\d+(?:\.\d{1,4})?)\b", user_text)
                if price_match:
                    val = price_match.group(1)
                    state[slot_name] = val
                    sm[slot_name] = val
                    filled[slot_name] = val

    return discovered_slot_names


def load_gecx_callback(agent_name, app_dir):
    agent_dir_path = os.path.join(app_dir, "agents")
    exact_agent_name = agent_name
    if os.path.isdir(agent_dir_path):
        for name in os.listdir(agent_dir_path):
            if name.lower() == agent_name.lower():
                exact_agent_name = name
                break

    cb_path = os.path.join(
        app_dir, "agents", exact_agent_name,
        "before_model_callbacks", "before_model_callbacks_01", "python_code.py"
    )
    if not os.path.exists(cb_path):
        cb_path = os.path.join(
            app_dir, "agents", exact_agent_name,
            "before_agent_callbacks", "before_agent_callbacks_01", "python_code.py"
        )

    spec = importlib.util.spec_from_file_location(f"cb_{exact_agent_name}", cb_path)
    cb_mod = importlib.util.module_from_spec(spec)
    cb_mod.__dict__["Part"] = Part
    cb_mod.__dict__["Content"] = Content
    cb_mod.__dict__["LlmResponse"] = LlmResponse
    cb_mod.__dict__["CallbackContext"] = Any
    cb_mod.__dict__["LlmRequest"] = Any
    cb_mod.__dict__["tools"] = MockTools(app_dir)
    spec.loader.exec_module(cb_mod)
    return cb_mod


def get_quick_action_chips(sm_state):
    return []


class VisualizerHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?") or self.path.startswith("/webwidget-deploy.html"):
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            with open(HTML_PATH, "r", encoding="utf-8") as f:
                self.wfile.write(f.read().encode("utf-8"))
        else:
            super().do_GET()

    def do_POST(self):
        global active_agent
        if self.path == "/chat":
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = json.loads(self.rfile.read(content_length).decode("utf-8"))

            session_id = post_data.get("sessionId", "default_session")
            user_session = get_user_session(session_id)
            session_sm = user_session["sm"]
            session_history = user_session["history"]

            target_agent = post_data.get("agent") or active_agent
            user_text = post_data.get("message", "").strip()
            is_reset = post_data.get("reset", False)
            channel = post_data.get("channel", session_sm.get("filled", {}).get("channel", "MOBILE"))

            if user_text.lower().startswith("/channel"):
                parts = user_text.split()
                if len(parts) > 1 and parts[1].upper() in ("MOBILE", "WEB"):
                    channel = parts[1].upper()
                    session_sm.setdefault("filled", {})["channel"] = channel
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "message": f"Channel switched to {channel}.",
                        "actions": [],
                        "state": {
                            "filled": session_sm.get("filled", {}),
                            "pending": session_sm.get("pending", {}),
                            "status": session_sm.get("status", "in_progress"),
                            "channel": channel
                        }
                    }).encode("utf-8"))
                    return

            if is_reset:
                user_session["sm"] = {"filled": {"channel": channel}}
                user_session["history"] = []
                user_session["hidden_tools"] = []
                session_sm = user_session["sm"]
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "message": "Session successfully reset! How can I assist you today?",
                    "actions": get_quick_action_chips(session_sm),
                    "state": {
                        "filled": {},
                        "pending": {},
                        "status": "in_progress"
                    }
                }).encode("utf-8"))
                return

            if session_sm.get("status") in ("complete", "escalated"):
                user_session["sm"] = {"filled": {"channel": channel}}
                user_session["history"] = []
                session_sm = user_session["sm"]
                session_history = user_session["history"]

            if user_text:
                session_history.append(("user", user_text))
                auto_introspect_dag_and_extract_slots(user_text, {"sm": session_sm}, APP_DIRECTORY, target_agent)

            state_dict = {
                "channel": channel,
                "sm": session_sm
            }

            contents = []
            for role, msg in session_history:
                c = Content(parts=[Part(text=msg)], role=role)
                contents.append(c)

            req = LlmRequest(contents=contents)
            mock_events = [MockEvent(is_user_flag=True)]

            cb = load_gecx_callback(target_agent, APP_DIRECTORY)
            context = CallbackContext(state_dict, last_user_text=user_text, events=mock_events)

            res = cb.before_model_callback(context, req)
            user_session["sm"] = state_dict["sm"]
            session_sm = user_session["sm"]
            user_session["hidden_tools"] = req.config.hidden_tools

            response_text = ""
            actions = []

            if res and hasattr(res, "content") and res.content and res.content.parts:
                for part in res.content.parts:
                    if getattr(part, "text", None):
                        response_text += part.text + "\n"
                    if getattr(part, "custom_payload", None):
                        cp = part.custom_payload
                        if isinstance(cp, dict):
                            if "payload" in cp and "actions" in cp["payload"]:
                                actions.extend(cp["payload"]["actions"])
                            elif "scenarios" in cp:
                                for sc in cp.get("scenarios", [])[:1]:
                                    for r_item in sc.get("responses", []):
                                        if r_item.get("type") == "text":
                                            response_text += r_item.get("text", "") + "\n"
                                        elif r_item.get("type") == "button":
                                            actions.append({
                                                "content": r_item.get("text", "Open Link"),
                                                "linkType": r_item.get("buttonType", "hyperLink"),
                                                "url": r_item.get("link", "#")
                                            })

            if not response_text.strip():
                response_text = session_sm.get("_next_directive") or session_sm.get("_system_message") or "How can I assist you?"

            if not actions and session_sm.get("status") != "complete":
                actions = get_quick_action_chips(session_sm)

            session_history.append(("model", response_text.strip()))

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "message": response_text.strip(),
                "actions": actions,
                "state": {
                    "filled": session_sm.get("filled", {}),
                    "pending": session_sm.get("pending", {}),
                    "status": session_sm.get("status", "in_progress")
                }
            }).encode("utf-8"))


def main():
    global APP_DIRECTORY, active_agent
    parser = argparse.ArgumentParser(description="Universal CXAS Slot-Filling Visualizer Server")
    parser.add_argument("--app-dir", default=DEFAULT_DIRECTORY, help="Path to CXAS app directory")
    parser.add_argument("--agent", default=DEFAULT_AGENT, help="Initial subagent name")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", DEFAULT_PORT)), help="Server port")
    args = parser.parse_args()

    APP_DIRECTORY = os.path.abspath(args.app_dir)
    active_agent = args.agent

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("", args.port), VisualizerHandler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
