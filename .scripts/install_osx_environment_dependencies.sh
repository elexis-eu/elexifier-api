set -e

echo "Installing osx dependencies"

echo "Installing psycopg2"
env LDFLAGS="-I/usr/local/opt/openssl/include -L/usr/local/opt/openssl/lib" pip3 install psycopg2

echo "Installing libmagic"
brew link libmagic
