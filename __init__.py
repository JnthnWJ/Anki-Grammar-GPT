import aqt
from aqt.qt import *
from aqt.utils import showInfo, tooltip
from aqt.editor import Editor
from aqt import gui_hooks

import sys
import os
import json
import re
import glob

print("DEBUG: __init__.py starting")

# Use Anki's get_config to retrieve addon config
def get_config():
    """Retrieves the configuration from Anki's managed config."""
    config = aqt.mw.addonManager.getConfig(__name__)
    print(f"DEBUG: config from Anki: {config}")
    return config

def get_api_key():
    """Retrieves the API key from the config file."""
    config = get_config()
    return config.get("api_key", "")

def get_model():
    """Retrieves the model from the config file."""
    config = get_config()
    return config.get("model", "gpt-4o")  # Default to gpt-4o if not specified

def remove_html_tags(text):
    """Removes HTML tags from a string."""
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text)

def check_grammar(fields):
    """Sends the card content to the OpenAI API for grammar checking."""
    api_key = get_api_key()
    model = get_model()
    print(f"DEBUG: Got API key: {api_key}")
    print(f"DEBUG: Using model: {model}")
    if not api_key:
        showInfo("Please set your OpenAI API key in the add-on config.")
        return None

    openai.api_key = api_key

    # Create a schema based on the fields
    fields_schema = {
        field_name: {"type": "string", "description": f"Corrected text for field: {field_name}"}
        for field_name in fields
    }

    json_schema = {
        "name": "corrected_fields_response",
        "type": "object",
        "properties": {
            "corrected_fields": {
                "type": "object",
                "properties": fields_schema,
                "required": list(fields.keys()),
                "additionalProperties": False
            }
        },
        "required": ["corrected_fields"],
        "additionalProperties": False
    }

    # Add the "schema" key here
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "corrected_fields_response",
            "schema": json_schema  # Include the schema dictionary
        }
    }

    # Prepare the messages for the API
    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant designed to enhance Anki cards. Your primary role is to correct spelling errors. If the card appears to need additional improvement based on its content (e.g., awkward phrasing or unclear wording), or if the user includes '!improve' in their message, you may also improve the grammar and optimize the wording for clarity and effective learning. Use your reasoning to decide what improvements are appropriate while keeping the user’s intent and context in mind. Usually, less is more, as the user may prefer informal language and shorter sentences. Focus primarily on spelling corrections, and avoid increasing wordiness; for example, do not replace 'don't' with 'do not.' Do not add ending punctuation unless it is already present in the text. I will provide HTML formatted text, please keep that formatting and if you want to add formatting of your own, use Anki supported HTML tags. Return the corrected or improved text in a JSON format matching the schema provided by the user. If no changes are needed, return the text unaltered."
        },
        {
            "role": "user",
            "content": "Correct the following text and return a JSON object containing the corrected fields based on this schema:\n" +
                       f"{json.dumps(json_schema, indent=2)}\n\n" +
                       "\n".join(f"{field}: {fields[field]}" for field, value in fields.items())
        }
    ]

    try:
        response = openai.chat.completions.create(
            model=model,
            messages=messages,
            response_format=response_format
        )
        corrected_text = response.choices[0].message.content
        print(f"DEBUG: Corrected text from OpenAI: {corrected_text}")

        # Parse the JSON response
        corrected_data = json.loads(corrected_text)
        return corrected_data.get("corrected_fields", {})

    except openai.BadRequestError as e:
        print(f"DEBUG: BadRequestError from OpenAI: {e}")
        if "refusal" in str(e).lower():
            showInfo("The model refused to process the request, likely due to safety reasons.")
        else:
            showInfo(f"An unexpected error occurred: {e}")
        return None

    except Exception as e:
        print(f"DEBUG: Exception during check_grammar: {e}")
        showInfo(f"Error during grammar check: {e}")
        return None

def on_grammar_check(editor: Editor):
    """Gets the fields from the editor and initiates the grammar check."""
    note = editor.note
    if not note:
        return

    # Get field names from the note
    field_names = note.keys()

    fields = {field_name: note[field_name] for field_name in field_names}

    corrected_fields = check_grammar(fields)
    if corrected_fields:
        # Update the fields in the editor
        for field_name, corrected_value in corrected_fields.items():
            if field_name in note:
                editor.note[field_name] = corrected_value

        editor.loadNote()
        tooltip("Grammar checked and fields updated.")

def add_grammar_check_button(buttons, editor: Editor, *args, **kwargs):
   """Adds a button to the editor for triggering the grammar check."""
   icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
   button = editor.addButton(
       icon_path,
       "check_grammar",
       lambda ed=editor: on_grammar_check(ed),
       tip="Check Grammar (Ctrl+Shift+G)",
       keys="Ctrl+Shift+G"
   )
   buttons.append(button)

def get_venv_site_packages_path(venv_path):
    """
    Gets the path to the site-packages directory within a virtual environment.

    This function is more robust than manually constructing the path, as it
    handles differences in virtual environment layouts across platforms and
    Python versions.

    Args:
        venv_path (str): The path to the virtual environment directory.

    Returns:
        str: The absolute path to the site-packages directory, or None if not found.
    """

    lib_dir = os.path.join(venv_path, "lib")
    if not os.path.isdir(lib_dir):
        print(f"DEBUG: lib directory not found: {lib_dir}")
        return None

    # Use glob to find the python directory, which may vary (e.g., python3.9, python3.10)
    python_dir_pattern = os.path.join(lib_dir, "python*")
    python_dir_matches = glob.glob(python_dir_pattern)

    if not python_dir_matches:
        print(f"DEBUG: No python directory found in {lib_dir}")
        return None

    # Assume the first match is the correct Python directory
    python_dir = python_dir_matches[0]

    site_packages_path = os.path.join(python_dir, "site-packages")
    if not os.path.isdir(site_packages_path):
        print(f"DEBUG: site-packages directory not found: {site_packages_path}")
        return None

    return site_packages_path

# Get the absolute path to the virtual environment directory
venv_dir = os.path.join(os.path.dirname(__file__), "venv")

# Get the site-packages path using the function
site_packages_dir = get_venv_site_packages_path(venv_dir)

if site_packages_dir:
    sys.path.insert(0, site_packages_dir)
    print("DEBUG: sys.path modified:", sys.path)
else:
    print("DEBUG: Could not find site-packages directory in virtual environment.")

try:
    import openai
except ImportError as e:
    print(f"DEBUG: Error importing openai: {e}")
    import traceback
    traceback.print_exc()

# Call add_grammar_check_button when the editor is initialized
gui_hooks.editor_did_init_buttons.append(add_grammar_check_button)