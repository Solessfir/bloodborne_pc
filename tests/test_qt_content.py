"""Qt content pages on disposable mods, patch files and real-format save fixtures."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))

if importlib.util.find_spec('PySide6'):
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
    from PySide6.QtWidgets import QApplication, QDialogButtonBox, QSpinBox
    import bbport_qt_content as content
    from test_launcher_character import make_folder, make_profile, make_slot
else:
    content = None


@unittest.skipIf(content is None, 'PySide6 is needed for native Qt pages')
class ContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.settings = {**content.backend.APP_DEFAULTS, 'user_dir': str(self.root / 'user'),
                         'game_dir': '', 'mods_dir': str(self.root / 'mods'),
                         'patches_dir': str(self.root / 'patches')}
        for name, replacement in [('DATA_DIR', self.root), ('PORT_DIR', self.root / 'port')]:
            mock = patch.object(content.backend, name, replacement)
            mock.start()
            self.addCleanup(mock.stop)
        for module, name, value in [(content.saves, 'scan', []), (content.bench, 'game_pids', [])]:
            mock = patch.object(module, name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        for name in ('information', 'critical'):
            mock = patch.object(content.QMessageBox, name)
            mock.start()
            self.addCleanup(mock.stop)
        mock = patch.object(content.QMessageBox, 'question', return_value=content.QMessageBox.StandardButton.Yes)
        self.question = mock.start()
        self.addCleanup(mock.stop)
        self.pages = []
        self.addCleanup(self.close_pages)

    def close_pages(self):
        for page in self.pages:
            page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def page(self, cls):
        page = cls(self.settings)
        self.pages.append(page)
        return page

    def make_saves(self, name='Hunter', slot=0, attributes=(17, 12, 9, 15, 7, 8)):
        return make_folder(Path(self.settings['user_dir']), {slot: make_slot(name, attributes)}, make_profile({slot: name}))

    def test_empty_saves_hide_unused_lists_and_restore_actions(self):
        page = self.page(content.SavesPage)
        self.assertTrue(page.backups.isHidden())
        self.assertTrue(all(action.isHidden() for action in page.backup_actions))
        page._show_sources([])
        self.assertTrue(page.sources.isHidden())
        self.assertTrue(page.import_button.isHidden())

    def test_mod_reorder_checks_rescan_and_hidden_patch_choices(self):
        for name in ('A', 'B'):
            folder = self.root / 'mods' / name / 'chr'
            folder.mkdir(parents=True)
            (folder / 'hunter.bin').write_bytes(b'mod')
        (self.root / 'mods/Broken').mkdir()
        (self.root / 'mods.json').write_text(json.dumps({'order': ['B', 'A'], 'disabled': ['B']}))
        patches = self.root / 'patches'
        patches.mkdir()
        (patches / 'other.xml').write_text('<Patch><Metadata Name="Shown" AppVer="01.09" '
                                         'isEnabled="true" Author="Hunter"/></Patch>')
        (self.root / 'patches.json').write_text(json.dumps({'enabled': ['hidden/on'], 'disabled': ['hidden/off']}))
        page = self.page(content.ModsPage)
        self.assertEqual(list(page._choices(page.mods)), ['B', 'A'])
        self.assertFalse(page._choices(page.mods)['B'])
        page.mods.setCurrentRow(1)
        page.move_mod(-1)
        page.mods.item(0).setCheckState(Qt.CheckState.Unchecked)
        page.patches.item(0).setCheckState(Qt.CheckState.Unchecked)
        page.rescan()
        self.assertEqual(list(page._choices(page.mods)), ['A', 'B'])
        self.assertFalse(page._choices(page.mods)['A'])
        self.assertIn('Broken: empty', page.mod_problems.text())
        page.save()
        mods = json.loads((self.root / 'mods.json').read_text())
        self.assertEqual(mods, {'order': ['A', 'B'], 'disabled': ['A', 'B']})
        chosen = json.loads((self.root / 'patches.json').read_text())
        self.assertEqual(chosen['enabled'], ['hidden/on'])
        self.assertEqual(chosen['disabled'], ['hidden/off', 'other.xml/Shown'])

    def test_empty_mod_lists_do_not_erase_unavailable_choices(self):
        before = {'order': ['Offline'], 'disabled': ['Offline']}
        (self.root / 'mods.json').write_text(json.dumps(before))
        (self.root / 'patches.json').write_text(json.dumps({'enabled': ['offline/patch']}))
        self.page(content.ModsPage).save()
        self.assertEqual(json.loads((self.root / 'mods.json').read_text()), before)
        self.assertEqual(json.loads((self.root / 'patches.json').read_text()), {'enabled': ['offline/patch']})

    def test_settings_only_collect_changes_and_share_the_parent_dictionary(self):
        page = self.page(content.SavesPage)
        self.settings['auto_backup'] = False
        page.save()
        self.assertFalse(self.settings['auto_backup'])
        page.fields['user_dir'].setText(str(self.root / 'new'))
        page.fields['auto_backup'].setChecked(False)
        page.save()
        self.assertEqual(self.settings['user_dir'], str(self.root / 'new'))
        self.assertIs(page.settings, self.settings)
        self.assertEqual(page.backup_button.objectName(), 'button:backup')
        self.assertEqual(page.characters_body.objectName(), 'characters')
        self.assertFalse(page.fields['exit_backup'].isChecked())
        page.fields['exit_backup'].setChecked(True)
        page.save()
        self.assertIs(self.settings['exit_backup'], True)

    def test_a_file_that_is_no_backup_is_refused_with_the_reason(self):
        page = self.page(content.SavesPage)
        junk = self.root / 'junk.zip'
        junk.write_bytes(b'not a zip')
        content.QMessageBox.critical.reset_mock()
        with patch.object(content.QFileDialog, 'getOpenFileName', return_value=(str(junk), '')):
            page.add_backup_file()
        self.assertIn('no Bloodborne save backup', content.QMessageBox.critical.call_args.args[2])
        self.assertEqual(page.backups.count(), 0)

    def test_import_and_restore_use_real_archives_and_preserve_previous_saves(self):
        folder = self.make_saves('Original')
        before = (folder / 'userdata0000').read_bytes()
        source_user = self.root / 'external'
        source = make_folder(source_user, {0: make_slot('Imported')}, make_profile({0: 'Imported'}))
        page = self.page(content.SavesPage)
        page.import_save(content.saves.SaveSet('Other port', source))
        self.assertEqual(content.character.read_file(folder / 'userdata0000').name, 'Imported')
        archives = content.saves.backups(Path(self.settings['user_dir']))
        self.assertEqual(len(archives), 1)
        self.assertEqual(archives[0].reason, 'import')
        page.restore_backup(archives[0])
        self.assertEqual((folder / 'userdata0000').read_bytes(), before)
        self.assertEqual(len(content.saves.backups(Path(self.settings['user_dir']))), 2)
        self.assertEqual(page.backups.count(), 2)

    def test_declined_restore_never_changes_saves(self):
        folder = self.make_saves()
        archive = content.saves.backup(Path(self.settings['user_dir']))
        page = self.page(content.SavesPage)
        before = (folder / 'userdata0000').read_bytes()
        self.question.return_value = content.QMessageBox.StandardButton.No
        page.restore_backup(content.saves.Backup(archive))
        self.assertEqual((folder / 'userdata0000').read_bytes(), before)
        self.assertEqual(len(content.saves.backups(Path(self.settings['user_dir']))), 1)

    def test_running_game_blocks_import_backup_restore_export_and_respec(self):
        folder = self.make_saves()
        page = self.page(content.SavesPage)
        before = (folder / 'userdata0000').read_bytes()
        with patch.object(content.bench, 'game_pids', return_value=[1234]), \
             patch.object(content.saves, 'backup') as backup, \
             patch.object(content.saves, 'import_set') as import_set, \
             patch.object(content.saves, 'restore') as restore, \
             patch.object(content.respec, 'respec') as respec:
            page.backup_now()
            page.import_save(content.saves.SaveSet('test', folder))
            page.restore_backup()
            page.export_saves()
            page.open_respec()
            for mock in (backup, import_set, restore, respec):
                mock.assert_not_called()
        page.set_game_running(True)
        self.assertFalse(page.import_button.isEnabled())
        self.assertFalse(page.restore_button.isEnabled())
        self.assertFalse(page.export_button.isEnabled())
        self.assertEqual((folder / 'userdata0000').read_bytes(), before)

    def test_export_add_rename_copy_and_failed_trash_leave_valid_backup(self):
        self.make_saves()
        page = self.page(content.SavesPage)
        export = self.root / 'export.zip'
        with patch.object(content.QFileDialog, 'getSaveFileName', return_value=(str(export), '')):
            page.export_saves()
        self.assertTrue(content.saves.Backup(export).ok)
        with patch.object(content.QInputDialog, 'getText', return_value=('My hunter', True)):
            page.rename_backup()
        selected = page._selected(page.backups)
        self.assertEqual(selected.label, 'My hunter')
        copy = self.root / 'copy.zip'
        with patch.object(content.QFileDialog, 'getSaveFileName', return_value=(str(copy), '')):
            page.copy_backup()
        self.assertEqual(copy.read_bytes(), selected.path.read_bytes())
        with patch.object(content.QFileDialog, 'getOpenFileName', return_value=(str(export), '')):
            page.add_backup_file()
        self.assertEqual(page.backups.count(), 2)
        with patch.object(content.saves, 'to_recycle_bin', return_value=False) as trash:
            page.delete_backup(selected)
        trash.assert_called_once_with(selected.path)
        self.assertTrue(selected.path.is_file())
        content.QMessageBox.critical.assert_called()

    def test_individual_character_restore_keeps_other_character(self):
        user = Path(self.settings['user_dir'])
        then = {0: make_slot('Maria'), 2: make_slot('Gehrmanling')}
        folder = make_folder(user, then, make_profile({0: 'Maria', 2: 'Gehrmanling'}, played=100))
        archive = content.saves.Backup(content.saves.backup(user))
        now = {0: make_slot('Maria', (18, 12, 9, 15, 7, 8)), 2: make_slot('Gehrmanling', (20, 12, 9, 15, 7, 8))}
        make_folder(user, now, make_profile({0: 'Maria', 2: 'Gehrmanling'}, played=900))
        page = self.page(content.SavesPage)
        page.restore_character(archive, 'userdata0002', content.character.read(then[2]))
        self.assertEqual((folder / 'userdata0002').read_bytes(), then[2])
        self.assertEqual((folder / 'userdata0000').read_bytes(), now[0])
        self.assertEqual(len(content.saves.backups(user)), 2)

    def test_respec_dialog_keeps_level_and_creates_safety_copy(self):
        folder = self.make_saves()
        page = self.page(content.SavesPage)
        def edit():
            dialog = QApplication.activeModalWidget()
            spins = dialog.findChildren(QSpinBox)
            spins[0].setValue(spins[0].value() + 1)
            spins[1].setValue(spins[1].value() - 1)
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Apply).click()
        QTimer.singleShot(0, edit)
        page.open_respec()
        info = content.character.read_file(folder / 'userdata0000')
        self.assertEqual(info.attributes['vitality'], 18)
        self.assertEqual(info.attributes['endurance'], 11)
        self.assertEqual(info.level, 18)
        self.assertTrue(list((Path(self.settings['user_dir']) / 'respec-backups').glob('*/SPRJ0005')))

    def test_choose_save_folder_survives_an_older_background_search(self):
        external = self.root / 'external'
        folder = make_folder(external, {0: make_slot('Imported')}, make_profile({0: 'Imported'}))
        page = self.page(content.SavesPage)
        context = (str(page.user_dir()), '', page._source_revision)
        with patch.object(content.QFileDialog, 'getExistingDirectory', return_value=str(external)):
            page.choose_save_folder()
        self.assertEqual(page._selected(page.sources).folder, folder)
        page._search_done(context, [], '')
        self.assertEqual(page._selected(page.sources).folder, folder)

    def test_folder_open_uses_native_desktop_and_pending_folder(self):
        page = self.page(content.ModsPage)
        folder = self.root / 'newmods'
        folder.mkdir()
        page.fields['mods_dir'].setText(str(folder))
        with patch.object(content.QDesktopServices, 'openUrl', return_value=True) as launch:
            content.open_path(page._folder_path('mods_dir'))
        self.assertEqual(launch.call_args.args[0].toLocalFile(), str(folder))


if __name__ == '__main__':
    unittest.main()
