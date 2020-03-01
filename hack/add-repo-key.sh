#!/bin/sh

# Script Source: https://github.com/billimek
# This script will, for the current repo:
# 1. delete any existing repo keys
# 2. add a new repo key from the input passed-in

if [ ! -f "$HOME/.secret/github_access_token" ]; then
  echo "$HOME/.secret/github_access_token needs to exist with a GitHub personal access token"
  exit 1
fi

if [ -z "$1" ]; then
  echo "This script requires a github username passed in as an argument"
  exit 1
else
  github_username="$1"
fi

if [ -z "$2" ]; then
  echo "This script requires an ssh-key passed in as an argument"
  exit 1
else
  KEY="$2"
fi

if [ -z "$3" ]; then
  echo "This script requires a repo name passed in as an argument"
  exit 1
else
  reponame="$3"
fi

need() {
    which "$1" &>/dev/null || die "Binary '$1' is missing but required"
}

need "git"
need "curl"
need "jq"

github_access_token=$(cat "$HOME"/.secret/github_access_token)

repo_id="github-deploy-$reponame.github.com"

# delete all existing deploy keys
curl \
    -H"Authorization: token $github_access_token"\
    https://api.github.com/repos/"$github_username"/"$reponame"/keys 2>/dev/null\
    | jq '.[] | .id ' | \
    while read _id; do
        echo "- deploy key: $_id"
        curl \
            -X "DELETE"\
            -H"Authorization: token $github_access_token"\
            https://api.github.com/repos/"$github_username"/"$reponame"/keys/"$_id" 2>/dev/null
    done
# add the keyfile to github
echo
echo "+ deploy key:"
echo -n ">> "
curl \
    -i\
    -H"Authorization: token $github_access_token"\
    --data @- https://api.github.com/repos/"$github_username"/"$reponame"/keys << EOF
{
"title" : "$repo_id $(date)",
"key" : "$KEY",
"read_only" : false
}
EOF
