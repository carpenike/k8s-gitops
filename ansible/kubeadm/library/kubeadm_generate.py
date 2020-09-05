#!/usr/bin/python
# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from ansible.module_utils.basic import AnsibleModule
from string import digits, ascii_lowercase
import random
from secrets import token_hex

DOCUMENTATION = '''
---
module: kubeadm_generate
short_description: Generates a kubeadm token or certificate key
description:
    - Generates a kubeadm token matching the format "[a-z0-9]{6}.[a-z0-9]{16}"
    - or a certificate key matching "[a-z0-9]{64}".
author:
    - RobReus <rob@devrobs.nl>
options:
    kind:
        description:
            - what to generate, token or certificate-key
        default: token
        choices:
            - token
            - certificate-key
        type: str
notes: []
'''

RETURN = '''
generated:
    description: the generated item
    returned: always
    type: str
    sample: a1b2c3.d4e5f6g7h8i9j0k1l2
kind:
    description: the kind of generated string
    returned: always
    type: str
    sample: token
'''

EXAMPLES = '''
- name: generate kubeadm token
  kubeadm_generate:
    kind: token
  register: token
'''

def_lang = ['env', 'LC_ALL=C']


def run_module():
    module_args = dict(
        kind=dict(type='str', required=False, default='token', choices=['token', 'certificate-key'])
    )
    result = dict(
        changed=True,
        generated='',
        kind=''
    )

    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)

    if module.params['kind'] == 'token':
        token = ''.join(random.choices(digits + ascii_lowercase, k=22))
        result['generated'] = f"{token[:6]}.{token[6:]}"
        result['kind'] = 'token'
    else:
        result['generated'] = token_hex(32)
        result['kind'] = 'certificate-key'

    module.exit_json(**result)


def main():
    run_module()


if __name__ == '__main__':
    main()
