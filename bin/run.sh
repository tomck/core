#!/usr/bin/env bash

set -e

unset CDPATH
cd "$( dirname "${BASH_SOURCE[0]}" )/.."

echo() { builtin echo -e "\e[1;7mSCITRAN\e[0;7m $@\e[27m"; }


USAGE="
    Usage:\n
    $0 [-T] [-U] [config file]\n
    \n
    -T: do not bootstrap testdata\n
    -U: do not users and groups
"

BOOTSTRAP_USERS=1
BOOTSTRAP_TESTDATA=1

while getopts ":TU" opt; do
    case $opt in
        T)
            BOOTSTRAP_TESTDATA=0;
            shift $((OPTIND-1));;
        U)
            BOOTSTRAP_USERS=0;
            shift $((OPTIND-1));;
        \?)
            echo "Invalid option: -$OPTARG" >&2
            echo $USAGE >&2
            exit 1
            ;;
    esac
done

set -o allexport


if [ "$#" -eq 1 ]; then
    EXISTING_ENV=$(env | grep "SCITRAN_" | cat)
    source "$1"
    eval "$EXISTING_ENV"
fi
if [ "$#" -gt 1 ]; then
    echo "Too many positional arguments"
    echo $USAGE >&2
    exit 1
fi


# Minimal default config values
SCITRAN_RUNTIME_HOST=${SCITRAN_RUNTIME_HOST:-"127.0.0.1"}
SCITRAN_RUNTIME_PORT=${SCITRAN_RUNTIME_PORT:-"8080"}
SCITRAN_RUNTIME_PATH=${SCITRAN_RUNTIME_PATH:-"./runtime"}
SCITRAN_RUNTIME_BOOTSTRAP=${SCITRAN_RUNTIME_BOOTSTRAP:-"bootstrap.json"}
SCITRAN_PERSISTENT_PATH=${SCITRAN_PERSISTENT_PATH:-"./persistent"}
SCITRAN_PERSISTENT_DATA_PATH=${SCITRAN_PERSISTENT_DATA_PATH:-"$SCITRAN_PERSISTENT_PATH/data"}
SCITRAN_PERSISTENT_DB_PATH=${SCITRAN_PERSISTENT_DB_PATH:-"$SCITRAN_PERSISTENT_PATH/db"}
SCITRAN_PERSISTENT_DB_PORT=${SCITRAN_PERSISTENT_DB_PORT:-"9001"}
SCITRAN_PERSISTENT_DB_URI=${SCITRAN_PERSISTENT_DB_URI:-"mongodb://localhost:$SCITRAN_PERSISTENT_DB_PORT/scitran"}
SCITRAN_CORE_DRONE_SECRET=${SCITRAN_CORE_DRONE_SECRET:-"change-me"}

[ -z "$SCITRAN_RUNTIME_SSL_PEM" ] && SCITRAN_SITE_API_URL="http" || SCITRAN_SITE_API_URL="https"
SCITRAN_SITE_API_URL="$SCITRAN_SITE_API_URL://$SCITRAN_RUNTIME_HOST:$SCITRAN_RUNTIME_PORT/api"

set +o allexport


if [ ! -f "$SCITRAN_RUNTIME_BOOTSTRAP" ]; then
    echo "Aborting. Please create $SCITRAN_RUNTIME_BOOTSTRAP from bootstrap.json.sample."
    exit 1
fi


if [ -f "`which brew`" ]; then
    echo "Homebrew is installed"
else
    echo "Installing Homebrew"
    ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"
    echo "Installed Homebrew"
fi

if brew list | grep -q openssl; then
    echo "OpenSSL is installed"
else
    echo "Installing OpenSSL"
    brew install openssl
    echo "Installed OpenSSL"
fi

if brew list | grep -q python; then
    echo "Python is installed"
else
    echo "Installing Python"
    brew install python
    echo "Installed Python"
fi

if [ -f "`which virtualenv`" ]; then
    echo "Virtualenv is installed"
else
    echo "Installing Virtualenv"
    pip install virtualenv
    echo "Installed Virtualenv"
fi

if [ -d "$SCITRAN_RUNTIME_PATH" ]; then
    echo "Virtualenv exists at $SCITRAN_RUNTIME_PATH"
else
    echo "Creating 'scitran' Virtualenv at $SCITRAN_RUNTIME_PATH"
    virtualenv -p `brew --prefix`/bin/python --prompt="(scitran) " $SCITRAN_RUNTIME_PATH
    echo "Created 'scitran' Virtualenv at $SCITRAN_RUNTIME_PATH"
fi


echo "Activating Virtualenv"
source $SCITRAN_RUNTIME_PATH/bin/activate

echo "Installing Python requirements"
bin/install.sh


# Install and launch MongoDB
install_mongo() {
    curl $MONGODB_URL | tar xz -C $VIRTUAL_ENV/bin --strip-components 2
    echo "MongoDB version $MONGODB_VERSION installed"
}

if [ ! -f "$SCITRAN_PERSISTENT_DB_PATH/mongod.lock" ]; then
    echo "Creating database location at $SCITRAN_PERSISTENT_DB_PATH"
    mkdir -p $SCITRAN_PERSISTENT_DB_PATH
fi

MONGODB_VERSION=$(cat mongodb_version.txt)
MONGODB_URL="https://fastdl.mongodb.org/osx/mongodb-osx-x86_64-$MONGODB_VERSION.tgz"
if [ -x "$VIRTUAL_ENV/bin/mongod" ]; then
    INSTALLED_MONGODB_VERSION=$($VIRTUAL_ENV/bin/mongod --version | grep "db version" | cut -d "v" -f 3)
    echo "MongoDB version $INSTALLED_MONGODB_VERSION is installed"
    if [ "$INSTALLED_MONGODB_VERSION" != "$MONGODB_VERSION" ]; then
        echo "Upgrading MongoDB to version $MONGODB_VERSION"
        install_mongo
    fi
else
    echo "Installing MongoDB"
    install_mongo
fi

ulimit -n 1024
mongod --dbpath $SCITRAN_PERSISTENT_DB_PATH --smallfiles --port $SCITRAN_PERSISTENT_DB_PORT &
MONGOD_PID=$!


# Set python path so scripts can work
export PYTHONPATH=.


# Serve API with PasteScript
TEMP_INI_FILE=$(mktemp -t scitran_api)
cat << EOF > $TEMP_INI_FILE
[server:main]
use = egg:Paste#http
host = $SCITRAN_RUNTIME_HOST
port = $SCITRAN_RUNTIME_PORT
ssl_pem=$SCITRAN_RUNTIME_SSL_PEM

[app:main]
paste.app_factory = api.api:app_factory
EOF

echo "Launching Paster application server"
paster serve --reload $TEMP_INI_FILE &
PASTER_PID=$!


# Set up exit and error trap to shutdown mongod and paster
trap "{
    echo 'Exit signal trapped';
    kill $MONGOD_PID $PASTER_PID; wait;
    rm -f $TEMP_INI_FILE
    deactivate
}" EXIT ERR


# Wait for everything to come up
sleep 2


# Boostrap users and groups
if [ $BOOTSTRAP_USERS -eq 1 ]; then
    if [ -f "$SCITRAN_PERSISTENT_DB_PATH/.bootstrapped" ]; then
        echo "Users previously bootstrapped. Remove $SCITRAN_PERSISTENT_DB_PATH to re-bootstrap."
    else
        echo "Bootstrapping users"
        bin/bootstrap.py --insecure --secret "$SCITRAN_CORE_DRONE_SECRET" $SCITRAN_SITE_API_URL "$SCITRAN_RUNTIME_BOOTSTRAP"
        echo "Bootstrapped users"
        touch "$SCITRAN_PERSISTENT_DB_PATH/.bootstrapped"
    fi
else
    echo "NOT bootstrapping users"
fi


# Boostrap test data
TESTDATA_REPO="https://github.com/scitran/testdata.git"
if [ $BOOTSTRAP_TESTDATA -eq 1 ]; then
    if [ -f "$SCITRAN_PERSISTENT_DATA_PATH/.bootstrapped" ]; then
        echo "Data previously bootstrapped. Remove $SCITRAN_PERSISTENT_DATA_PATH to re-bootstrap."
    else
        if [ ! -d "$SCITRAN_PERSISTENT_PATH/testdata" ]; then
            echo "Cloning testdata to $SCITRAN_PERSISTENT_PATH/testdata"
            git clone --single-branch $TESTDATA_REPO $SCITRAN_PERSISTENT_PATH/testdata
        else
            echo "Updating testdata in $SCITRAN_PERSISTENT_PATH/testdata"
            git -C $SCITRAN_PERSISTENT_PATH/testdata pull
        fi
        echo "Bootstrapping testdata"
        UPLOAD_URI=$SCITRAN_SITE_API_URL/upload/label?secret=$SCITRAN_CORE_DRONE_SECRET
        folder_uploader --yes --insecure "$SCITRAN_PERSISTENT_PATH/testdata" $UPLOAD_URI
        echo "Bootstrapped testdata"
        touch "$SCITRAN_PERSISTENT_DATA_PATH/.bootstrapped"
    fi
else
    echo "NOT bootstrapping testdata"
fi


# Wait for good or bad things to happen until exit or error trap catches
wait
