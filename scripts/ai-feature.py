#!/usr/bin/env python3
import json
import sys
from pathlib import Path

STATE_FILE = Path(".ai-workflow-state.json")
TEMPLATE_PATH = Path("docs/features/template/README.md")


def load_state():
    if STATE_FILE.exists():
        with STATE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {"phase": "idle", "current_subtask": None, "ticket_id": None}


def save_state(state):
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def main():
    if len(sys.argv) < 2:
        print("Usage: ai-feature <command> [args]")
        print("Commands: start <ticket-id>, status, approve, reset")
        sys.exit(1)

    state = load_state()
    command = sys.argv[1]

    if command == "start":
        if len(sys.argv) < 3:
            print("Error: ticket-id required")
            sys.exit(1)
        ticket = sys.argv[2]
        state["ticket_id"] = ticket
        state["phase"] = "analysis"
        save_state(state)

        feature_dir = Path("docs/features") / ticket
        feature_dir.mkdir(parents=True, exist_ok=True)
        readme_path = feature_dir / "README.md"

        if not readme_path.exists() and TEMPLATE_PATH.exists():
            content = TEMPLATE_PATH.read_text(encoding="utf-8").replace(
                "{{ticket_id}}", ticket
            )
            readme_path.write_text(content, encoding="utf-8")
            print(f"Initialized {readme_path} from template.")

        print(f"Feature {ticket} started. Current phase: analysis.")

    elif command == "status":
        print(f"Ticket ID: {state.get('ticket_id')}")
        print(f"Phase: {state.get('phase')}")
        print(f"Current Subtask: {state.get('current_subtask')}")

    elif command == "approve":
        transitions = {
            "analysis": "plan",
            "plan": "execute",
            "execute": "final",
        }
        current = state["phase"]
        if current in transitions:
            state["phase"] = transitions[current]
            save_state(state)
            print(
                f"{current.capitalize()} approved. Current phase: {state['phase']}."
            )
        else:
            print(f"Cannot approve in phase: {current}")

    elif command == "reset":
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        print("Workflow state reset.")

    else:
        print(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
