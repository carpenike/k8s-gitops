#! /bin/bash
# Verifies that files passed in are encrypted
set -e

has_error=0
for file in $@ ; do
    head -1 "$file" | grep --quiet '^\$ANSIBLE_VAULT;' || {
        if [ -s "$file" ]; then
            echo "ERROR: $file is not encrypted"
            has_error=1
        else
            echo "WARNING: $file is not encrypted but is empty"
        fi
    }
done

if [ $has_error -eq 1 ] ; then
    echo "To ignore, use --no-verify"
fi

exit $has_error
