#!/usr/bin/env python3
"""Process a Tic Tac Toe move submitted via a GitHub issue.

Reads the game state from ``tictactoe/state.json``, applies the move,
detects wins/draws, regenerates the README block between the
``TICTACTOE:START`` / ``TICTACTOE:END`` markers, and emits an output
snippet that the workflow uses to comment on the triggering issue.

Inputs are passed via environment variables so the script stays trivially
testable from the command line:

  TTT_ISSUE_TITLE   - title of the triggering issue (e.g. ``tictactoe: move 4``)
  TTT_ISSUE_USER    - GitHub login of the player who opened the issue
  TTT_REPO          - ``owner/repo`` (used to build "new move" links)
  TTT_STATE_PATH    - path to state.json (default: tictactoe/state.json)
  TTT_README_PATH   - path to README.md   (default: README.md)
  TTT_COMMENT_PATH  - path to write the issue comment body (optional)
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE = REPO_ROOT / "tictactoe" / "state.json"
DEFAULT_README = REPO_ROOT / "README.md"

WIN_LINES = [
    (0, 1, 2), (3, 4, 5), (6, 7, 8),  # rows
    (0, 3, 6), (1, 4, 7), (2, 5, 8),  # columns
    (0, 4, 8), (2, 4, 6),             # diagonals
]

START_MARK = "<!-- TICTACTOE:START -->"
END_MARK = "<!-- TICTACTOE:END -->"

CELL_EMPTY = " "
PLAYERS = ("X", "O")


def parse_move(title: str) -> int | None:
    """Extract a 1-9 cell number from the issue title.

    Accepts variants like ``tictactoe: move 4``, ``ttt move 4``, or just
    ``tictactoe 4``. Returns the 0-indexed cell, or ``None`` if no valid
    digit was found.
    """
    if not title:
        return None
    match = re.search(r"[1-9]", title)
    if not match:
        return None
    return int(match.group(0)) - 1


def check_winner(board: list[str]) -> tuple[str | None, list[int] | None]:
    for line in WIN_LINES:
        a, b, c = line
        if board[a] != CELL_EMPTY and board[a] == board[b] == board[c]:
            return board[a], list(line)
    return None, None


def reset_board(state: dict, starting_player: str) -> None:
    state["board"] = [CELL_EMPTY] * 9
    state["next_player"] = starting_player
    state["winner"] = None
    state["winning_line"] = None
    state["is_draw"] = False
    state["move_count"] = 0
    state["last_move_by"] = None
    state["last_move_cell"] = None


def cell_glyph(value: str) -> str:
    if value == "X":
        return "❌"
    if value == "O":
        return "⭕"
    return ""


def new_move_url(repo: str, cell: int) -> str:
    # cell is 0-indexed; surface 1-indexed in the title for humans.
    title = f"tictactoe: move {cell + 1}"
    body = (
        "Just press **Submit new issue** to play this move.\n\n"
        "A GitHub Action will pick up your move, update the board on the "
        "profile README, and comment back here with the result."
    )
    from urllib.parse import quote
    return (
        f"https://github.com/{repo}/issues/new"
        f"?title={quote(title)}&body={quote(body)}"
    )


def render_board_markdown(state: dict, repo: str) -> str:
    board = state["board"]
    winning = set(state.get("winning_line") or [])
    rows = ["|     |     |     |", "| :-: | :-: | :-: |"]
    for r in range(3):
        cells = []
        for c in range(3):
            i = r * 3 + c
            value = board[i]
            if value == CELL_EMPTY and not state["winner"] and not state["is_draw"]:
                url = new_move_url(repo, i)
                cells.append(f"[**{i + 1}**]({url})")
            elif value == CELL_EMPTY:
                cells.append(f"`{i + 1}`")
            else:
                glyph = cell_glyph(value)
                cells.append(f"**{glyph}**" if i in winning else glyph)
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def render_status(state: dict, repo: str) -> str:
    lines: list[str] = []
    if state["winner"]:
        lines.append(f"🏆 **{cell_glyph(state['winner'])} ({state['winner']}) wins!**")
        lines.append("")
        lines.append(
            f"Click any cell above to start **Game #{state['game_number'] + 1}** — "
            f"**{cell_glyph(state['next_player'])} ({state['next_player']})** moves first."
        )
    elif state["is_draw"]:
        lines.append("🤝 **It's a draw!**")
        lines.append("")
        lines.append(
            f"Click any cell above to start **Game #{state['game_number'] + 1}** — "
            f"**{cell_glyph(state['next_player'])} ({state['next_player']})** moves first."
        )
    else:
        lines.append(
            f"➡️ **Next turn:** {cell_glyph(state['next_player'])} "
            f"(**{state['next_player']}**) — click any numbered cell above to play."
        )
    lines.append("")
    scores = state["scores"]
    lines.append(
        f"**Scoreboard** — ❌ X: `{scores['X']}` &nbsp;|&nbsp; "
        f"⭕ O: `{scores['O']}` &nbsp;|&nbsp; 🤝 Draws: `{scores['draws']}` "
        f"&nbsp;|&nbsp; 🎮 Game: `#{state['game_number']}`"
    )
    if state["last_move_by"]:
        lines.append("")
        lines.append(
            f"Last move: cell **{state['last_move_cell'] + 1}** by "
            f"[@{state['last_move_by']}](https://github.com/{state['last_move_by']})"
        )
    return "\n".join(lines)


def render_history(state: dict) -> str:
    history = state.get("history", [])[-5:]
    if not history:
        return ""
    lines = ["", "<details><summary>📜 Recent moves</summary>", ""]
    for entry in reversed(history):
        lines.append(
            f"- Game #{entry['game']} · {cell_glyph(entry['player'])} "
            f"`{entry['player']}` → cell **{entry['cell'] + 1}** "
            f"by [@{entry['user']}](https://github.com/{entry['user']}) "
            f"— {entry['result']}"
        )
    lines.append("")
    lines.append("</details>")
    return "\n".join(lines)


def render_block(state: dict, repo: str) -> str:
    parts = [
        "## 🎮 Live Tic Tac Toe — Powered by GitHub Actions",
        "",
        "> Click any numbered cell to play your move. A GitHub Action will "
        "process it and update the board for everyone.",
        "",
        render_board_markdown(state, repo),
        "",
        render_status(state, repo),
        render_history(state),
    ]
    return "\n".join(p for p in parts if p is not None)


def update_readme(readme_path: Path, block: str) -> None:
    text = readme_path.read_text(encoding="utf-8")
    if START_MARK not in text or END_MARK not in text:
        # Append the block (with markers) at the end of the README.
        new_text = text.rstrip() + "\n\n" + START_MARK + "\n" + block + "\n" + END_MARK + "\n"
    else:
        pattern = re.compile(
            re.escape(START_MARK) + r".*?" + re.escape(END_MARK),
            re.DOTALL,
        )
        new_text = pattern.sub(START_MARK + "\n" + block + "\n" + END_MARK, text)
    readme_path.write_text(new_text, encoding="utf-8")


def apply_move(state: dict, cell: int, user: str) -> dict:
    """Apply ``cell`` (0-indexed) to the state, mutating it in place.

    Returns a result dict describing what happened, used to build the
    issue comment.
    """
    # If the previous game ended, automatically start a new one so the
    # incoming move kicks off the next round.
    if state["winner"] or state["is_draw"]:
        starting_player = state["next_player"]  # already toggled at game end
        state["game_number"] += 1
        reset_board(state, starting_player)

    if state["board"][cell] != CELL_EMPTY:
        return {
            "ok": False,
            "reason": (
                f"Cell **{cell + 1}** is already taken by "
                f"**{state['board'][cell]}**. Please pick an empty cell."
            ),
        }

    player = state["next_player"]
    state["board"][cell] = player
    state["move_count"] += 1
    state["last_move_by"] = user
    state["last_move_cell"] = cell

    winner, line = check_winner(state["board"])
    result_text: str
    if winner:
        state["winner"] = winner
        state["winning_line"] = line
        state["scores"][winner] += 1
        # Loser starts the next game (classic playground rule).
        state["next_player"] = "O" if winner == "X" else "X"
        result_text = f"🏆 {winner} wins!"
    elif state["move_count"] == 9:
        state["is_draw"] = True
        state["scores"]["draws"] += 1
        # Alternate who starts after a draw.
        state["next_player"] = "O" if player == "X" else "X"
        result_text = "🤝 Draw"
    else:
        state["next_player"] = "O" if player == "X" else "X"
        result_text = f"next: {state['next_player']}"

    state["history"].append({
        "game": state["game_number"],
        "player": player,
        "cell": cell,
        "user": user,
        "result": result_text,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    # Cap history length to keep the file small.
    state["history"] = state["history"][-50:]

    return {"ok": True, "player": player, "result": result_text}


def build_comment(state: dict, move_result: dict, user: str, repo: str) -> str:
    if not move_result["ok"]:
        return (
            f"🚫 Sorry @{user}, that move isn't valid.\n\n"
            f"{move_result['reason']}\n\n"
            "Head back to the [profile README]"
            f"(https://github.com/{repo}#readme) and click an empty cell."
        )
    lines = [
        f"✅ Move accepted! @{user} played **{move_result['player']}** "
        f"on cell **{state['last_move_cell'] + 1}**.",
        "",
        render_board_markdown(state, repo),
        "",
        render_status(state, repo),
        "",
        f"Thanks for playing! See the live board on the "
        f"[profile README](https://github.com/{repo}#readme).",
    ]
    return "\n".join(lines)


def write_output(comment_path: Path | None, comment: str, close_issue: bool) -> None:
    # Always echo to stdout for log visibility.
    print("---comment-start---")
    print(comment)
    print("---comment-end---")

    if comment_path:
        comment_path.write_text(comment, encoding="utf-8")

    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as fh:
            fh.write(f"close_issue={'true' if close_issue else 'false'}\n")


def main() -> int:
    title = os.environ.get("TTT_ISSUE_TITLE", "")
    user = os.environ.get("TTT_ISSUE_USER", "anonymous")
    repo = os.environ.get("TTT_REPO", "RamachandraKulkarni/RamachandraKulkarni")
    state_path = Path(os.environ.get("TTT_STATE_PATH", str(DEFAULT_STATE)))
    readme_path = Path(os.environ.get("TTT_README_PATH", str(DEFAULT_README)))
    comment_path_env = os.environ.get("TTT_COMMENT_PATH")
    comment_path = Path(comment_path_env) if comment_path_env else None

    cell = parse_move(title)
    state = json.loads(state_path.read_text(encoding="utf-8"))

    if cell is None:
        comment = (
            f"🤔 Hi @{user}, I couldn't find a cell number (1-9) in the "
            f"issue title `{title!r}`.\n\n"
            "Open a new issue with a title like `tictactoe: move 5` — or, "
            "easier, just click a cell on the "
            f"[profile README](https://github.com/{repo}#readme)."
        )
        write_output(comment_path, comment, close_issue=True)
        return 0

    move_result = apply_move(state, cell, user)
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    update_readme(readme_path, render_block(state, repo))

    comment = build_comment(state, move_result, user, repo)
    write_output(comment_path, comment, close_issue=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
