# python3 couldn't be linked to python while this script is being executed.
# It is linked after the execution though - in the terminal.
# This could/should be improved.

set -e

# Python 3 is a requirement
# TODO: Add installation script for linux
echo "Installing python"
if [[ "$OSTYPE" == "darwin"* ]]; then
  set +e

  # This will install the latest python, which is currently 3.7
  brew install python@3

  echo "Linking python to the new version"
  # Change to ~/.bash_profile if you're not using .zshrc
  # https://stackoverflow.com/questions/3557037/appending-a-line-to-a-file-only-if-it-does-not-already-exist
  grep -qF 'alias python' ~/.zshrc || echo 'alias python=python3' >> ~/.zshrc
  grep -qF 'alias pip' ~/.zshrc || echo 'alias pip=pip3' >> ~/.zshrc

  echo "Verifying python version"
  python --version
fi

echo "Installing virtualenv"
pip3 install virtualenv

echo "Specifying the path to python 3 binary"

if [[ "$OSTYPE" == "darwin"* ]]; then
  # OSX
  virtualenv -p /usr/local/bin/python3.* venv
else
  # Linux
  virtualenv -p /usr/bin/python3.* venv
fi

echo "Activating virtual environment"
source venv/bin/activate

echo "Installing requirements.txt"
pip3 install -r requirements.txt

# https://stackoverflow.com/questions/394230/how-to-detect-the-os-from-a-bash-script
if [[ "$OSTYPE" == "darwin"* ]]; then
  echo "Installing osx environment dependencies"
  /bin/bash ./.scripts/install_osx_environment_dependencies.sh
fi

echo "Executing the database setup"
/bin/bash ./.scripts/setup_database.sh

# TODO: This needs to go out as soon as possible
echo "Creating the first user"
python3 create_user.py

echo "Your elexifier-api is ready. Run python run.py to run the local server."
