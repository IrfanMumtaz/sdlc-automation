"""
Minimal Trello REST API wrapper. Deliberately dumb — no caching, no retries beyond
basic error surfacing. The orchestrator is the only thing that should get clever;
this module just talks to Trello.

Auth: Trello's own API key/token (NOT the claude.ai Trello connector). Get both
from your Power-Up's API key page at https://trello.com/power-ups/admin.

The key and token go in the Authorization header rather than the query string,
so a failed request's error message (which includes the URL) doesn't leak them
into logs or an agent's context.
"""

import requests
import config

BASE_URL = "https://api.trello.com/1"


def _headers():
    return {"Authorization": f'OAuth oauth_consumer_key="{config.TRELLO_KEY}", oauth_token="{config.TRELLO_TOKEN}"'}


def _request(method, path, files=None, **params):
    resp = requests.request(method, f"{BASE_URL}/{path}", headers=_headers(), params=params, files=files, timeout=60)
    resp.raise_for_status()
    return resp.json()


def get_cards_on_board():
    """
    Return all open cards on the board, with their current list ID. `pos` is the
    card's position in its list (smaller is nearer the top) and `labels` carries
    the priority labels; the router sorts on both.
    """
    return _request("GET", f"boards/{config.BOARD_ID}/cards",
                    fields="id,name,idList,pos,labels,dateLastActivity")


def get_card(card_id):
    """
    Return one card's name, description, current list ID, position and labels.
    `card_id` may be the card's id or the short link from its URL.
    """
    return _request("GET", f"cards/{card_id}", fields="id,name,desc,idList,pos,labels")


def get_card_comments(card_id):
    """Return comment actions on a card, newest first."""
    return _request("GET", f"cards/{card_id}/actions", filter="commentCard", limit=50)


def add_comment(card_id, text):
    return _request("POST", f"cards/{card_id}/actions/comments", text=text)


def move_card(card_id, list_id):
    return _request("PUT", f"cards/{card_id}", idList=list_id)


def update_card_description(card_id, description):
    return _request("PUT", f"cards/{card_id}", desc=description)


def get_attachments(card_id):
    return _request("GET", f"cards/{card_id}/attachments", fields="id,name")


def delete_attachment(card_id, attachment_id):
    return _request("DELETE", f"cards/{card_id}/attachments/{attachment_id}")


def add_attachment(card_id, file_path, name):
    with open(file_path, "rb") as f:
        return _request("POST", f"cards/{card_id}/attachments", files={"file": (name, f)}, name=name)


def whoami():
    """The Trello account the credentials belong to; used to check them."""
    return _request("GET", "members/me", fields="username,fullName")


def get_board(board_ref):
    """A board by its id or short link (the part after /b/ in its URL)."""
    return _request("GET", f"boards/{board_ref}", fields="id,name,url")


def get_open_lists(board_id):
    return _request("GET", f"boards/{board_id}/lists", filter="open", fields="id,name,pos")


def get_board_labels(board_id):
    return _request("GET", f"boards/{board_id}/labels", fields="id,name,color", limit=1000)


def create_label(board_id, name, color):
    return _request("POST", "labels", idBoard=board_id, name=name, color=color)


def create_list(board_id, name, pos="bottom"):
    return _request("POST", "lists", idBoard=board_id, name=name, pos=pos)
