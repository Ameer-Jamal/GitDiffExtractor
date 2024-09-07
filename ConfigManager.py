import json
import os


class ConfigManager:
    def __init__(self, config_file='config.json'):
        self.config_file = config_file
        self.config = {
            "last_repo_dir": "",
            "last_output_dir": ""
        }
        self.load_config()

    def load_config(self):
        """ Load the configuration from the file if it exists. """
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as file:
                self.config = json.load(file)

    def save_config(self):
        """ Save the current configuration to the file. """
        with open(self.config_file, 'w') as file:
            json.dump(self.config, file)

    def set_repo_dir(self, directory):
        """ Set the last repository directory. """
        self.config['last_repo_dir'] = directory
        self.save_config()

    def set_output_dir(self, directory):
        """ Set the last output directory. """
        self.config['last_output_dir'] = directory
        self.save_config()

    def get_repo_dir(self):
        """ Get the last used repository directory. """
        return self.config.get('last_repo_dir', '')

    def get_output_dir(self):
        """ Get the last used output directory. """
        return self.config.get('last_output_dir', '')
