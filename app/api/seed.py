"""API-Router: Seed-Board Initialization — create GitHub issues for idea cards.

Route: POST /api/seed?action=init-github
"""
import logging
from fastapi import APIRouter, HTTPException, Query

from app.services import board_service
from app.services.github_seed_service import create_issue_for_card
from app.services.board_service import set_card_github_issue_id

log = logging.getLogger("dashboard.api.seed")
router = APIRouter(tags=["seed"])


@router.post("/seed")
def seed_init_github(board_id: str = Query(default=""), action: str = Query(default="init-github")):
    """Initialize GitHub issues for idea cards in a board.

    Query params:
        board_id: board to process (required)
        action: "init-github" (default) — create issues for all idea cards without issue_id

    Returns:
        {
            "status": "ok" | "error",
            "board_id": str,
            "action": str,
            "cards_processed": int,
            "issues_created": int,
            "errors": [{"card_id": str, "title": str, "error": str}, ...]
        }
    """
    if not board_id.strip():
        raise HTTPException(status_code=400, detail="board_id is required")
    if action != "init-github":
        raise HTTPException(status_code=400, detail=f"action '{action}' not supported")

    try:
        board = board_service.get_board(board_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Board '{board_id}' not found")
    except Exception as e:
        log.error("Error loading board %s: %s", board_id, e)
        raise HTTPException(status_code=500, detail=f"Error loading board: {e}")

    result = {
        "status": "ok",
        "board_id": board_id,
        "action": action,
        "cards_processed": 0,
        "issues_created": 0,
        "errors": [],
    }

    # Find all idea cards without github_issue_id
    for column in board.get("columns", []):
        for card in column.get("cards", []):
            card_id = card.get("id", "")
            if not card_id:
                continue

            # Skip if already has github_issue_id
            if card.get("github_issue_id"):
                log.debug("Card %s already has github_issue_id, skipping", card_id)
                continue

            # Skip if has old github_issue field (already has an issue)
            if card.get("github_issue"):
                log.debug("Card %s already has github_issue field, skipping", card_id)
                continue

            result["cards_processed"] += 1
            title = card.get("title", f"Idea: {card_id}")
            description = card.get("description") or card.get("desc", "")

            # Create GitHub issue
            issue_result = create_issue_for_card(
                card_id=card_id,
                title=title,
                description=description,
                labels=["idea", "seed"]
            )

            if issue_result.get("status") == "created":
                issue_url = issue_result.get("issue_url", "")
                issue_number = issue_result.get("issue_number", "")
                log.info("Created GitHub issue #%s for card %s: %s", issue_number, card_id, issue_url)
                result["issues_created"] += 1

                # Store issue URL in card
                try:
                    set_card_github_issue_id(board_id, card_id, issue_url)
                    log.debug("Stored github_issue_id in card %s", card_id)
                except Exception as e:
                    log.error("Failed to store issue URL in card %s: %s", card_id, e)
                    result["errors"].append({
                        "card_id": card_id,
                        "title": title,
                        "error": f"issue created but failed to store URL: {e}"
                    })
            else:
                error = issue_result.get("error", "unknown error")
                log.warning("Failed to create issue for card %s: %s", card_id, error)
                # Only add to errors if it's not a "skipped" status (no auth)
                if issue_result.get("status") != "skipped":
                    result["errors"].append({
                        "card_id": card_id,
                        "title": title,
                        "error": error
                    })

    log.info(
        "seed init-github for board %s: processed %d cards, created %d issues, %d errors",
        board_id, result["cards_processed"], result["issues_created"], len(result["errors"])
    )
    return result
