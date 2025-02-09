# __init__.py
import sys
import os
import glob
import pprint
import re
import json
from typing import Dict, Type, List

from aqt import mw, gui_hooks
from aqt.qt import *
from aqt.editor import Editor
from aqt.utils import showInfo, tooltip

def get_venv_site_packages_path(venv_path):
    """Gets the path to the site-packages directory."""
    lib_dir = os.path.join(venv_path, "lib")
    if not os.path.isdir(lib_dir):
        return None
    python_dir_pattern = os.path.join(lib_dir, "python*")
    python_dir_matches = glob.glob(python_dir_pattern)
    if not python_dir_matches:
        return None
    python_dir = python_dir_matches[0]
    site_packages_path = os.path.join(python_dir, "site-packages")
    if not os.path.isdir(site_packages_path):
        return None
    return site_packages_path

venv_dir = os.path.join(os.path.dirname(__file__), "venv")
site_packages_dir = get_venv_site_packages_path(venv_dir)
if site_packages_dir:
    sys.path.insert(0, site_packages_dir)
else:
    print("DEBUG: Failed to find site-packages in venv")

print("DEBUG: Full sys.path:")
pprint.pprint(sys.path)

from pydantic import BaseModel, Field, ValidationError, create_model
from openai import OpenAI, APIConnectionError, RateLimitError, APIStatusError

print("DEBUG: __init__.py starting")

def get_config():
    """Retrieves the configuration."""
    return mw.addonManager.getConfig(__name__)

def get_api_key():
    """Retrieves the API key."""
    return get_config().get("api_key", "")

def get_model():
    """Retrieves the model."""
    return get_config().get("model", "openai/gpt-4o")

def remove_html_tags(text):
    """Removes HTML tags."""
    return re.sub('<.*?>', '', text)

def create_dynamic_pydantic_model(fields: Dict[str, str]) -> Type[BaseModel]:
    """Creates a Pydantic model for corrected fields."""
    field_definitions = {
        field_name: (str, Field(..., description=f"Corrected text for field: {field_name}"))
        for field_name in fields if field_name != "OriginalContent"
    }
    return create_model("CorrectedFields", **field_definitions)

def check_grammar(fields: Dict[str, str]):
    """Sends card content for grammar checking."""
    api_key = get_api_key()
    model_name = get_model()

    if not api_key:
        showInfo("Please set your API key.")
        return None

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    CorrectedFieldsModel = create_dynamic_pydantic_model(fields)
    # --- JSON Schema Modification (Key Change) ---
    json_schema = CorrectedFieldsModel.schema() # Expect a single object Now.

    prompt_parts = [
        "You are a helpful assistant designed to enhance Anki cards. Your primary role is to correct spelling errors. If the card appears to need additional improvement based on its content (e.g., awkward phrasing or unclear wording), or if the user includes '!improve' in their message, you may also improve the grammar and optimize the wording for clarity and effective learning. Use your reasoning to decide what improvements are appropriate while keeping the user’s intent and context in mind. Usually, less is more, as the user may prefer informal language and shorter sentences. Focus primarily on spelling corrections, and avoid increasing wordiness; for example, do not shorten contractions: Don't replace 'don't' with 'do not.' Do not add ending punctuation unless it is already present in the text. I will provide HTML formatted text, please keep that formatting and if you want to add formatting of your own, use Anki supported HTML tags. Return the corrected or improved text in a JSON format matching the schema provided. If no changes are needed, return the text unaltered.",
        "Correct the following text and return a JSON object containing the corrected fields:",
        *[f"{field}: {value}" for field, value in fields.items() if field != "OriginalContent"],
    ]
    prompt = "\n".join(prompt_parts)

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": json_schema},
            extra_headers={"HTTP-Referer": "your_anki_addon_identifier", "X-Title": "Anki-Grammar-GPT"},
        )

        print(f"DEBUG: Raw response from OpenRouter: {response}")

        if response.choices and response.choices[0].message.content:
            corrected_json_str = response.choices[0].message.content

            try:
                match = re.search(r"```json\n(.*?)```", corrected_json_str, re.DOTALL)
                if match:
                    corrected_json_str = match.group(1).strip()
                corrected_data = json.loads(corrected_json_str) # Load directly as a dict now.
                corrected_fields = CorrectedFieldsModel(**corrected_data)
                return corrected_fields.dict() # No more list handling.

            except (json.JSONDecodeError, ValidationError) as e:
                showInfo("Error parsing or validating the model's response.")
                print(f"DEBUG: Error: {e}\nResponse: {corrected_json_str}")
                return None
        else:
            showInfo("No content returned.")
            return None

    except (RateLimitError, APIConnectionError, APIStatusError, Exception) as e:
        showInfo(f"An error occurred: {e}")
        return None

def on_grammar_check(editor: Editor):
    """Gets fields and initiates grammar check."""
    note = editor.note
    if not note:
        return

    field_names = note.keys()
    original_content_field_present = "OriginalContent" in field_names

    if original_content_field_present:
        original_content = json.dumps({field_name: note[field_name] for field_name in field_names})
        note["OriginalContent"] = original_content
        editor.loadNote()

    fields = {field_name: note[field_name] for field_name in field_names}
    corrected_fields = check_grammar(fields)

    if corrected_fields:
        for field_name, corrected_value in corrected_fields.items():
            if field_name in note:
                editor.note[field_name] = corrected_value
        editor.loadNote()
        tooltip("Grammar checked." if original_content_field_present else "Undo not available. Grammar checked.")

def on_undo(editor: Editor):
    """Restores original content."""
    note = editor.note
    if not note or "OriginalContent" not in note:
        tooltip("No changes to undo.")
        return

    try:
        original_content = json.loads(note["OriginalContent"])
        for field_name, original_value in original_content.items():
            if field_name != "OriginalContent":
                note[field_name] = original_value
        note["OriginalContent"] = ""
        editor.loadNote()
        tooltip("Changes undone.")
    except json.JSONDecodeError:
        showInfo("Error decoding original content.")

def add_grammar_check_button(buttons, editor: Editor, *args, **kwargs):
    """Adds a grammar check button."""
    icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
    buttons.append(editor.addButton(icon_path, "check_grammar", lambda ed=editor: on_grammar_check(ed), tip="Check Grammar (Ctrl+Shift+G)", keys="Ctrl+Shift+G"))

def add_undo_button(buttons, editor: Editor, *args, **kwargs):
    """Adds an undo button."""
    icon_path = os.path.join(os.path.dirname(__file__), "undo_icon.png")
    buttons.append(editor.addButton(icon_path, "undo", lambda ed=editor: on_undo(ed), tip="Undo Changes (Ctrl+Z)", keys="Ctrl+Z"))

gui_hooks.editor_did_init_buttons.append(add_grammar_check_button)
gui_hooks.editor_did_init_buttons.append(add_undo_button)