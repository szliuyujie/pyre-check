# Copyright (c) 2016-present, Facebook, Inc.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

# pyre-unsafe

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, mock_open, patch

from ... import errors, upgrade
from ...repository import Repository
from .. import targets_to_configuration
from ..targets_to_configuration import TargetsToConfiguration


repository = Repository()


class TargetsToConfigurationTest(unittest.TestCase):
    @patch("builtins.open")
    @patch(f"{targets_to_configuration.__name__}.Repository.revert_all")
    @patch(f"{targets_to_configuration.__name__}.Repository.add_paths")
    @patch(f"{targets_to_configuration.__name__}.find_targets")
    @patch(f"{targets_to_configuration.__name__}.get_filesystem")
    @patch.object(Path, "exists")
    @patch(f"{targets_to_configuration.__name__}.remove_non_pyre_ignores")
    @patch(f"{targets_to_configuration.__name__}.Configuration.get_errors")
    @patch(f"{targets_to_configuration.__name__}.add_local_mode")
    @patch.object(upgrade.ErrorSuppressingCommand, "_suppress_errors")
    @patch(f"{targets_to_configuration.__name__}.Repository.format")
    @patch(
        f"{targets_to_configuration.__name__}.TargetsToConfiguration.remove_target_typing_fields"
    )
    def test_convert_directory(
        self,
        remove_target_typing_fields,
        repository_format,
        suppress_errors,
        add_local_mode,
        get_errors,
        remove_non_pyre_ignores,
        path_exists,
        get_filesystem,
        find_targets,
        add_paths,
        revert_all,
        open_mock,
    ) -> None:
        arguments = MagicMock()
        arguments.subdirectory = "subdirectory"
        arguments.lint = True
        arguments.glob = None
        arguments.fixme_threshold = None
        arguments.no_commit = False
        find_targets.return_value = {
            "subdirectory/a": ["target_one"],
            "subdirectory/b/c": ["target_three", "target_two"],
        }
        filesystem_list = MagicMock()
        filesystem_list.return_value = []
        get_filesystem.list = filesystem_list
        path_exists.return_value = False
        pyre_errors = [
            {
                "line": 2,
                "column": 4,
                "path": "local.py",
                "code": 7,
                "name": "Kind",
                "concise_description": "Error",
                "inference": {},
                "ignore_error": False,
                "external_to_global_root": False,
            }
        ]

        # Create local project configuration
        get_errors.side_effect = [
            errors.Errors(pyre_errors),
            errors.Errors(pyre_errors),
        ]
        with patch("json.dump") as dump_mock:
            mocks = [mock_open(read_data="{}").return_value]
            open_mock.side_effect = mocks
            TargetsToConfiguration(arguments, repository).convert_directory(
                Path("subdirectory")
            )
            expected_configuration_contents = {
                "targets": [
                    "//subdirectory/a:target_one",
                    "//subdirectory/b/c:target_three",
                    "//subdirectory/b/c:target_two",
                ],
                "strict": True,
            }
            open_mock.assert_has_calls(
                [call(Path("subdirectory/.pyre_configuration.local"), "w")]
            )
            dump_mock.assert_called_once_with(
                expected_configuration_contents, mocks[0], indent=2, sort_keys=True
            )
            suppress_errors.assert_has_calls([call(errors.Errors(pyre_errors))])
            add_local_mode.assert_not_called()
            add_paths.assert_called_once_with(
                [Path("subdirectory/.pyre_configuration.local")]
            )
            remove_target_typing_fields.assert_called_once()

        # Add to existing local project configuration
        suppress_errors.reset_mock()
        open_mock.reset_mock()
        dump_mock.reset_mock()
        remove_target_typing_fields.reset_mock()
        path_exists.return_value = True
        get_errors.side_effect = [
            errors.Errors(pyre_errors),
            errors.Errors(pyre_errors),
        ]
        configuration_contents = json.dumps({"targets": ["//existing:target"]})
        with patch("json.dump") as dump_mock:
            mocks = [
                mock_open(read_data=configuration_contents).return_value,
                mock_open(read_data="{}").return_value,
            ]
            open_mock.side_effect = mocks
            TargetsToConfiguration(arguments, repository).convert_directory(
                Path("subdirectory")
            )
            expected_configuration_contents = {
                "targets": [
                    "//existing:target",
                    "//subdirectory/a:target_one",
                    "//subdirectory/b/c:target_three",
                    "//subdirectory/b/c:target_two",
                ]
            }
            open_mock.assert_has_calls(
                [
                    call(Path("subdirectory/.pyre_configuration.local")),
                    call(Path("subdirectory/.pyre_configuration.local"), "w"),
                ]
            )
            dump_mock.assert_called_once_with(
                expected_configuration_contents, mocks[1], indent=2, sort_keys=True
            )
        suppress_errors.assert_has_calls([call(errors.Errors(pyre_errors))])
        add_local_mode.assert_not_called()
        remove_target_typing_fields.assert_called_once()

    @patch(f"{targets_to_configuration.__name__}.find_files")
    @patch(f"{targets_to_configuration.__name__}.Repository.submit_changes")
    @patch(
        f"{targets_to_configuration.__name__}.TargetsToConfiguration.convert_directory"
    )
    def test_run_targets_to_configuration(
        self, convert_directory, submit_changes, find_files
    ) -> None:
        arguments = MagicMock()
        arguments.subdirectory = "subdirectory"
        arguments.lint = True
        arguments.glob = None
        arguments.fixme_threshold = None
        arguments.no_commit = False

        find_files.return_value = ["subdirectory/.pyre_configuration.local"]
        TargetsToConfiguration(arguments, repository).run()
        convert_directory.assert_called_once_with(Path("subdirectory"))
        submit_changes.assert_called_once()

        convert_directory.reset_mock()
        find_files.return_value = [
            "subdirectory/a/.pyre_configuration.local",
            "subdirectory/b/.pyre_configuration.local",
        ]
        TargetsToConfiguration(arguments, repository).run()
        convert_directory.assert_has_calls(
            [call(Path("subdirectory/a")), call(Path("subdirectory/b"))]
        )

        convert_directory.reset_mock()
        find_files.return_value = [
            "subdirectory/a/.pyre_configuration.local",
            "subdirectory/a/nested/.pyre_configuration.local",
        ]
        TargetsToConfiguration(arguments, repository).run()
        convert_directory.assert_called_once_with(Path("subdirectory/a"))

    @patch("subprocess.check_output")
    def test_deduplicate_targets(self, mock_check_output) -> None:
        configuration = upgrade.Configuration(Path("test"), {"targets": ["//a:a"]})
        configuration.deduplicate_targets()
        expected_targets = ["//a:a"]
        self.assertEqual(expected_targets, configuration.targets)

        mock_check_output.side_effect = [b"a", b"b"]
        configuration = upgrade.Configuration(
            Path("test"), {"targets": ["//a/...", "//b/..."]}
        )
        configuration.deduplicate_targets()
        expected_targets = ["//a/...", "//b/..."]
        self.assertEqual(expected_targets, configuration.targets)

        mock_check_output.side_effect = [b"a", b"a"]
        configuration = upgrade.Configuration(
            Path("test"), {"targets": ["//a/...", "//b/..."]}
        )
        configuration.deduplicate_targets()
        expected_targets = ["//a/..."]
        self.assertEqual(expected_targets, configuration.targets)

        mock_check_output.side_effect = [b"a", b"a\nb"]
        configuration = upgrade.Configuration(
            Path("test"), {"targets": ["//a/...", "//b/..."]}
        )
        configuration.deduplicate_targets()
        expected_targets = ["//a/...", "//b/..."]
        self.assertEqual(expected_targets, configuration.targets)

        mock_check_output.side_effect = [b"a", b"//c:c"]
        configuration = upgrade.Configuration(
            Path("test"), {"targets": ["//a/...", "//b/...", "//c:c"]}
        )
        configuration.deduplicate_targets()
        expected_targets = ["//a/...", "//b/..."]
        self.assertEqual(expected_targets, configuration.targets)

        mock_check_output.side_effect = [b"//a/b:x\n//a/b:y"]
        configuration = upgrade.Configuration(
            Path("test"), {"targets": ["//a/b:", "//a/b:x"]}
        )
        configuration.deduplicate_targets()
        expected_targets = ["//a/b:"]
        self.assertEqual(expected_targets, configuration.targets)