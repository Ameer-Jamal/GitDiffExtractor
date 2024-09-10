import json
import os

import json
import os
import shutil
import tempfile


class ConfigManager:
    def __init__(self, config_file='config.json'):
        self.config_file = config_file
        self.config = {
            "last_repo_dir": "",
            "last_output_dir": "",
            "origin_branch": ""
        }
        self.load_config()

    def save_config(self):
        """ Save the current configuration to the file in a more robust way. """
        try:
            # Ensure the directory for the config file exists
            config_dir = os.path.dirname(self.config_file)
            if config_dir and not os.path.exists(config_dir):
                os.makedirs(config_dir)

            # Check if we can write to the directory
            if config_dir and not os.access(config_dir, os.W_OK):
                raise PermissionError(f"Cannot write to directory: {config_dir}")

            # Write to a temporary file first
            with tempfile.NamedTemporaryFile('w', delete=False, dir=config_dir) as temp_file:
                json.dump(self.config, temp_file, indent=4)
                temp_file_path = temp_file.name

            # Explicitly close the temporary file
            temp_file.close()

            # Replace the old config file with the new one
            shutil.move(temp_file_path, self.config_file)

        except PermissionError as e:
            print(f"Permission error: {e}")
        except Exception as e:
            print(f"Error saving config: {e}")

    def load_config(self):
        """ Load the configuration from the file if it exists. """
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as file:
                    self.config = json.load(file)
            except json.JSONDecodeError as e:
                print(f"Error loading JSON: {e}")
            except Exception as e:
                print(f"Error reading config file: {e}")
    def set_repo_dir(self, repo_dir):
        """ Set the last repository directory and save the config. """
        self.config["last_repo_dir"] = repo_dir
        self.save_config()

    def set_output_dir(self, output_dir):
        """ Set the last output directory and save the config. """
        self.config["last_output_dir"] = output_dir
        self.save_config()

    def set_origin_branch(self, origin_branch):
        """ Set the origin branch and save the config. """
        self.config["origin_branch"] = origin_branch
        self.save_config()

    def get_repo_dir(self):
        return self.config.get("last_repo_dir", "")

    def get_output_dir(self):
        return self.config.get("last_output_dir", "")

    def get_origin_branch(self):
        return self.config.get("origin_branch", "")

    def __del__(self):
        """ Ensure config is saved on application exit. """
        self.save_config()
