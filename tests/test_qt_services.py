"""Qt service pages use temporary profiles, mocked services and offscreen rendering."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))

if importlib.util.find_spec('PySide6'):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    import bbport_qt_services as qt
    import bbport_theme_qt as theme
else:
    qt = None


@unittest.skipIf(qt is None, 'PySide6 is needed for the Qt launcher')
class QtServicesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        theme.apply(cls.app)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        self.settings = {**qt.backend.APP_DEFAULTS, 'user_dir': str(self.data / 'user')}
        self.profile_patch = patch.multiple(qt.backend, DATA_DIR=self.data, PORT_DIR=self.data)
        self.profile_patch.start()
        self.addCleanup(self.profile_patch.stop)
        self.pages = []
        self.addCleanup(self.cleanup_pages)

    def cleanup_pages(self):
        for page in self.pages:
            if isinstance(page, qt.OnlinePage):
                page.shutdown()
            page.close()
            page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def page(self, cls):
        page = cls(self.settings)
        self.pages.append(page)
        return page

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(predicate())

    def test_online_supermedo_is_the_pool_and_own_server_hides(self):
        self.settings.update(online_pool='huntersdream')
        page = self.page(qt.OnlinePage)
        self.assertEqual(page.pool.currentData(), 'supermedo')
        self.assertFalse(page.supermedo_card.isHidden())
        self.assertFalse(page.party_card.isHidden())
        self.assertTrue(page.shadnet_card.isHidden())
        page.save()
        self.assertEqual(self.settings['online_pool'], 'supermedo')

    def test_account_is_saved_only_when_it_changes(self):
        page = self.page(qt.OnlinePage)
        self.settings.update(supermedo_npid='setup-hunter', supermedo_pass='setup-pass')
        page.save()
        self.assertEqual((self.settings['supermedo_npid'], self.settings['supermedo_pass']), ('setup-hunter', 'setup-pass'))
        page.refresh(self.settings)
        self.assertEqual(page.account.text(), 'Signed in as setup-hunter')
        self.assertTrue(page.signed_out.isHidden())
        page.sign_out()
        page.save()
        self.assertEqual((self.settings['supermedo_npid'], self.settings['supermedo_pass']), ('', ''))
        self.assertFalse(page.signed_out.isHidden())
        self.assertTrue(page.register_box.isHidden())
        page.toggle_register()
        self.assertFalse(page.register_box.isHidden())

    def test_online_unchanged_quick_flags_do_not_override_shared_updates(self):
        page = self.page(qt.OnlinePage)
        page.fields['online_upnp'].setChecked(not page.fields['online_upnp'].isChecked())
        page.save()
        online = not page.fields['online'].isChecked()
        self.settings['online'] = online
        page.save()
        self.assertEqual(self.settings['online'], online)

    def test_discord_sign_in_runs_off_ui_thread(self):
        page = self.page(qt.OnlinePage)
        worker_threads = []

        def sign_in(server, on_page):
            worker_threads.append(threading.get_ident())
            on_page('https://example.invalid/auth')
            return 'hunter', 'secret'

        with patch.object(qt.backend, 'discord_sign_in', side_effect=sign_in), patch.object(qt, '_open') as browser:
            page.sign_in()
            self.wait_for(lambda: page.account.text() == 'Signed in as hunter')
            self.app.processEvents()
        self.assertNotEqual(worker_threads[0], threading.get_ident())
        browser.assert_called_once_with('https://example.invalid/auth')
        page.save()
        self.assertEqual((self.settings['supermedo_npid'], self.settings['supermedo_pass']), ('hunter', 'secret'))
        with patch.object(qt.backend, 'discord_sign_in', side_effect=OSError('denied')), \
                patch.object(qt.backend, 'connection_error', side_effect=lambda error, _url: str(error)):
            page.sign_out()
            page.sign_in()
            self.wait_for(lambda: 'denied' in page.signing.text())
        self.assertEqual(page.account.text(), 'Not signed in')

    def test_password_sign_in_and_new_account_check_with_the_server(self):
        page = self.page(qt.OnlinePage)
        page.sign_in_password()
        self.assertIn('Online ID', page.login_line.text())
        page.login_npid.setText('hunter')
        page.login_password.setText('wrong')
        with patch.object(qt.backend.bbport_signin, 'password_problem', return_value='Wrong password.'):
            page.sign_in_password()
            self.wait_for(lambda: page.login_line.text() == 'Wrong password.')
        self.assertEqual(page.account.text(), 'Not signed in')
        page.login_password.setText('right')
        with patch.object(qt.backend.bbport_signin, 'password_problem', return_value=None):
            page.sign_in_password()
            self.wait_for(lambda: page.account.text() == 'Signed in as hunter')
        self.assertEqual(page.login_password.text(), '')
        page.sign_out()
        page.toggle_register()
        page.new_npid.setText('newbie')
        page.new_password.setText('pass')
        page.email.setText('newbie@example.invalid')
        with patch.object(qt.backend.bbport_signin, 'register_problem', return_value=None) as register:
            page.create_account()
            self.wait_for(lambda: page.account.text() == 'Signed in as newbie')
        register.assert_called_once_with('newbie', 'pass', 'newbie@example.invalid')

    def test_party_signs_in_once_and_shows_the_hunters(self):
        self.settings.update(supermedo_npid='hunter', supermedo_pass='secret')
        page = self.page(qt.OnlinePage)
        party = {'party': {'code': 'SM-AAAA-BBBB', 'size': 4, 'members': [
            {'name': 'hunter', 'host': True, 'online': True, 'level': 50}, {'name': 'friend', 'online': False}]}}
        calls = []

        def call(name, body=None, key=''):
            calls.append((name, key))
            return (200, {'key': 'party-key'}) if name == 'signin' else (200, party)
        with patch.object(qt.backend, 'party_call', side_effect=call):
            page.party_act('host')
            self.wait_for(lambda: page.party_code.text() == 'SM-AAAA-BBBB')
        self.assertEqual(calls, [('signin', ''), ('host', 'party-key')])
        self.assertIn('friend', page.roster.text())
        self.assertEqual(page.kick_layout.count(), 2)  # one Kick button and the stretch
        page.save()
        self.assertEqual(self.settings['party_key'], 'party-key')
        page.sign_out()
        page.save()
        self.assertEqual(self.settings['party_key'], '')

    def test_connection_checks_supermedo_and_reports_offline(self):
        self.settings.update(online=False)
        page = self.page(qt.OnlinePage)
        with patch.object(qt.backend, 'server_check', return_value='reachable') as check:
            page.check_connection()
            self.wait_for(lambda: page.check_button.isEnabled())
        self.assertIn('reachable', page.result.text())
        self.assertIn('Not signed in', page.result.text())
        self.assertIn('starts offline', page.result.text())
        self.assertEqual(check.call_args.args[:2], (qt.backend.SUPERMEDO_SERVER, qt.backend.SUPERMEDO_WEBAPI))
        page.set_game_running(True)
        self.assertFalse(page.sign_in_button.isEnabled())
        self.assertFalse(page.fields['online_upnp'].isEnabled())

    def test_trophies_refresh_filters_and_external_runtime_log(self):
        user = Path(self.settings['user_dir'])
        user.mkdir()
        (user / 'trophies.log').write_text('14 1700000000\n')
        page = self.page(qt.TrophiesPage)
        self.assertEqual(page.summary.text(), '1 of 40 trophies earned')
        self.assertEqual(len(page.cards), 40)
        self.assertFalse(qt._trophy_icon(qt.trophies.BRONZE, True).isNull())
        page.filter.setCurrentIndex(page.filter.findData('earned'))
        self.assertEqual(list(page.cards), [14])
        self.assertEqual(page.cards[14].findChild(qt.QLabel, 'trophyName').text(), 'Father Gascoigne')
        (user / 'last_run.log').write_text('Runtime: trophy 15 unlocked\n')
        page.refresh()
        self.assertEqual(page.summary.text(), '2 of 40 trophies earned')
        self.assertIn('15 ', (user / 'trophies.log').read_text())

    def test_trophies_import_adds_unlocks_from_another_installation(self):
        old = self.data / 'old'
        old.mkdir()
        (old / 'trophies.log').write_text('14 1700000000\n')
        Path(self.settings['user_dir']).mkdir()
        page = self.page(qt.TrophiesPage)
        yes = qt.QMessageBox.StandardButton.Yes
        with patch.object(qt.backend.saves, 'trophy_records', return_value=[('Old port', old / 'trophies.log')]), \
                patch.object(qt.QMessageBox, 'question', return_value=yes) as ask, \
                patch.object(qt.QMessageBox, 'information') as told, \
                patch.object(qt.QMessageBox, 'critical', side_effect=AssertionError):
            page.import_trophies()
            self.wait_for(lambda: told.called)
        self.assertIn('Old port: 1 new here', ask.call_args.args[2])
        self.assertIn('14 ', (Path(self.settings['user_dir']) / 'trophies.log').read_text())
        self.assertEqual(page.summary.text(), '1 of 40 trophies earned')
        self.assertEqual(page.import_note.text(), page.import_hint)

    def test_help_game_files_check_runs_in_background_and_updates_stay_windows_only(self):
        game = self.data / 'game'
        (game / 'dvdroot_ps4').mkdir(parents=True)
        self.settings['game_dir'] = str(game)
        started = threading.Event()

        def check(folder, progress):
            started.set()
            progress(50, 100)
            return {'checked': 3, 'differ': ['a.bin'], 'missing': []}
        with patch.object(qt.HelpPage, 'check_installation'), \
                patch.dict(sys.modules, game_files=SimpleNamespace(check=check)):
            page = self.page(qt.HelpPage)
            page.check_game_files()
            self.assertFalse(page.files_button.isEnabled())
            self.wait_for(lambda: page.files_button.isEnabled())
        self.assertTrue(started.is_set())
        self.assertIn('1 of 3 game files differ', page.files_note.text())
        for key in ('button:updates', 'button:versions'):
            self.assertEqual(page.findChild(qt.QPushButton, key).isEnabled(), os.name == 'nt')
        self.settings['game_dir'] = ''
        page.check_game_files()
        self.assertEqual(page.files_note.text(), 'No game folder chosen yet.')

    def test_hardware_rating_reuses_probe_and_rejects_cross_vendor_override(self):
        cpu = qt.hardware.cpu_from_name('AMD Ryzen 7 5700X')
        with patch.object(qt, '_detect_hardware', return_value=('NVIDIA GeForce RTX 4070, discrete, 12288 MiB', cpu, 32)) as detect:
            page = self.page(qt.SystemPage)
            self.wait_for(lambda: detect.called and not page._checking)
        self.assertIsNotNone(page.rating)
        self.assertIn('Ryzen', page.status.text())
        amd = next(gpu for gpu in qt.hardware.GPU_LIST if gpu.vendor == 'amd')
        page.override.setCurrentIndex(page.override.findData(amd.id))
        self.assertEqual(page.override.currentData(), '')
        page.save()
        self.assertEqual(self.settings['gpu_override'], '')

    def test_help_checks_actions_cache_and_redacted_report(self):
        self.settings.update(online_password='password', supermedo_pass='test-pass', online_npid='hunter')
        with patch.object(qt.help_service, 'run_checks', return_value=([('warn', 'version', 'Install 1.09')], {'key': 'cache', 'state': 'clean'})) as check:
            page = self.page(qt.HelpPage)
            self.wait_for(lambda: check.called and not page._checking)
        self.assertIn('Install 1.09', page.check_result.text())
        self.assertTrue(page.topics['version'].property('problemDetected'))
        self.assertTrue(page.topic_bodies['version'][1].isHidden())
        page.open_topic('version')
        self.assertFalse(page.topic_bodies['version'][1].isHidden())
        page.save()
        self.assertEqual(self.settings['eboot_check']['key'], 'cache')
        requested = []
        page.page_requested.connect(requested.append)
        page._action('open_backups')
        self.assertEqual(requested, ['saves'])
        page.set_game_running(True)
        self.assertTrue(all(not button.isEnabled() for button in page.cache_buttons))
        target = self.data / 'report.zip'
        with patch.object(qt.QFileDialog, 'getSaveFileName', return_value=(str(target), '')), patch.object(qt.backend, 'ini_path', return_value=self.data / 'missing.ini'):
            page.save_report()
            self.wait_for(lambda: page.report_note.text().startswith('Saved:'))
        with zipfile.ZipFile(target) as report:
            settings = json.loads(report.read('settings.json'))
        for key in ('online_password', 'supermedo_pass', 'online_npid'):
            self.assertEqual(settings[key], '(hidden)')

    def test_service_errors_are_visible_and_every_page_renders(self):
        with patch.object(qt, '_detect_hardware', side_effect=OSError('no probe')), patch.object(qt.help_service, 'run_checks', side_effect=OSError('missing files')):
            pages = [self.page(cls) for cls in (qt.OnlinePage, qt.TrophiesPage, qt.SystemPage, qt.HelpPage)]
            self.wait_for(lambda: 'no probe' in pages[2].status.text() and 'missing files' in pages[3].check_result.text())
            for page in pages:
                page.resize(1050, 740)
                page.show()
                self.app.processEvents()
                self.assertFalse(page.grab().isNull())


if __name__ == '__main__':
    unittest.main()
