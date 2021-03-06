"""Sanity test for ansible-doc."""
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import collections
import os
import re

from lib.sanity import (
    SanitySingleVersion,
    SanityFailure,
    SanitySuccess,
    SanitySkipped,
    SanityMessage,
)

from lib.util import (
    SubprocessError,
    display,
)

from lib.util_common import (
    intercept_command,
)

from lib.ansible_util import (
    ansible_environment,
)

from lib.config import (
    SanityConfig,
)

from lib.data import (
    data_context,
)

from lib.coverage_util import (
    coverage_context,
)


class AnsibleDocTest(SanitySingleVersion):
    """Sanity test for ansible-doc."""
    def test(self, args, targets):
        """
        :type args: SanityConfig
        :type targets: SanityTargets
        :rtype: TestResult
        """
        settings = self.load_settings(args, None)

        targets_include = [target for target in targets.include if os.path.splitext(target.path)[1] == '.py']
        targets_include = settings.filter_skipped_targets(targets_include)

        paths = [target.path for target in targets_include]

        # This should use documentable plugins from constants instead
        plugin_type_blacklist = set([
            # not supported by ansible-doc
            'action',
            'doc_fragments',
            'filter',
            'netconf',
            'terminal',
            'test',
        ])

        modules = sorted(set(m for i in targets_include for m in i.modules))

        plugins = [os.path.splitext(i.path)[0].split('/')[-2:] + [i.path] for i in targets_include if
                   os.path.basename(i.path) != '__init__.py' and
                   re.search(r'^lib/ansible/plugins/[^/]+/', i.path)
                   and i.path != 'lib/ansible/plugins/cache/base.py']

        doc_targets = collections.defaultdict(list)
        target_paths = collections.defaultdict(dict)

        for module in modules:
            doc_targets['module'].append(data_context().content.prefix + module)

        for plugin_type, plugin_name, plugin_path in plugins:
            if plugin_type in plugin_type_blacklist:
                continue

            doc_targets[plugin_type].append(data_context().content.prefix + plugin_name)
            target_paths[plugin_type][data_context().content.prefix + plugin_name] = plugin_path

        if not doc_targets:
            return SanitySkipped(self.name)

        target_paths['module'] = dict((data_context().content.prefix + t.module, t.path) for t in targets.targets if t.module)

        env = ansible_environment(args, color=False)
        error_messages = []

        for doc_type in sorted(doc_targets):
            cmd = ['ansible-doc', '-t', doc_type] + sorted(doc_targets[doc_type])

            try:
                with coverage_context(args):
                    stdout, stderr = intercept_command(args, cmd, target_name='ansible-doc', env=env, capture=True)

                status = 0
            except SubprocessError as ex:
                stdout = ex.stdout
                stderr = ex.stderr
                status = ex.status

            if stderr:
                errors = stderr.strip().splitlines()
                messages = [self.parse_error(e, target_paths) for e in errors]

                if messages and all(messages):
                    error_messages += messages
                    continue

            if status:
                summary = u'%s' % SubprocessError(cmd=cmd, status=status, stderr=stderr)
                return SanityFailure(self.name, summary=summary)

            if stdout:
                display.info(stdout.strip(), verbosity=3)

            if stderr:
                summary = u'Output on stderr from ansible-doc is considered an error.\n\n%s' % SubprocessError(cmd, stderr=stderr)
                return SanityFailure(self.name, summary=summary)

        error_messages = settings.process_errors(error_messages, paths)

        if error_messages:
            return SanityFailure(self.name, messages=error_messages)

        return SanitySuccess(self.name)

    @staticmethod
    def parse_error(error, target_paths):
        """
        :type error: str
        :type target_paths: dict[str, dict[str, str]]
        :rtype: SanityMessage | None
        """
        # example error messages from lib/ansible/cli/doc.py:
        #   ERROR! module ping missing documentation (or could not parse documentation): expected string or buffer
        #   [ERROR]: module ping has a documentation error formatting or is missing documentation.
        match = re.search(r'^[^ ]*ERROR[^ ]* (?P<type>[^ ]+) (?P<name>[^ ]+) (?P<text>.*)$', error)

        if match:
            groups = match.groupdict()

            error_type = groups['type']
            error_name = groups['name']
            error_text = groups['text']

            if error_name in target_paths.get(error_type, {}):
                return SanityMessage(
                    message=error_text,
                    path=target_paths[error_type][error_name],
                )

        return None
