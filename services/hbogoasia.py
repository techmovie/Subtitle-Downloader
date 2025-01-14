#!/usr/bin/python3
# coding: utf-8

"""
This module is to download subtitle from HBOGO Asia
"""

import re
import os
import shutil
import platform
import logging
import sys
import uuid
from getpass import getpass
from pathlib import Path
from urllib.parse import urlparse
from configs.config import Platform
from utils.helper import driver_init, get_locale, download_files
from utils.subtitle import convert_subtitle
from services.service import Service

from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By


class HBOGOAsia(Service):
    def __init__(self, args):
        super().__init__(args)
        self.logger = logging.getLogger(__name__)
        self._ = get_locale(__name__, self.locale)

        self.credential = self.config.credential(Platform.HBOGO)
        self.username = args.email if args.email else self.credential['username']
        self.password = args.password if args.password else self.credential['password']

        self.subtitle_language = args.subtitle_language

        self.language_list = ()
        self.device_id = str(uuid.uuid4())
        self.origin = ""
        self.territory = ""
        self.channel_partner_id = ""
        self.session_token = ""
        self.multi_profile_id = ""

        self.api = {
            'geo': 'https://api2.hbogoasia.com/v1/geog?lang=zh-Hant&version=0&bundleId={bundle_id}',
            'login': 'https://api2.hbogoasia.com/v1/hbouser/login?lang=zh-Hant',
            'device': 'https://api2.hbogoasia.com/v1/hbouser/device?lang=zh-Hant',
            'tvseason': 'https://api2.hbogoasia.com/v1/tvseason/list?parentId={parent_id}&territory={territory}',
            'tvepisode': 'https://api2.hbogoasia.com/v1/tvepisode/list?parentId={parent_id}&territory={territory}',
            'movie': 'https://api2.hbogoasia.com/v1/movie?contentId={content_id}&territory={territory}',
            'playback': 'https://api2.hbogoasia.com/v1/asset/playbackurl?territory={territory}&contentId={content_id}&sessionToken={session_token}&channelPartnerID={channel_partner_id}&operatorId=SIN&lang=zh-Hant'
        }

    def get_language_code(self, lang):
        language_code = {
            'ENG': 'en',
            'CHN': 'zh-Hant',
            'CHC': 'zh-Hant',
            'CHZ': 'zh-Hans',
            'MAL': 'ms',
            'THA': 'th',
            'IND': 'id',
        }

        if language_code.get(lang):
            return language_code.get(lang)

    def get_language_list(self):
        if not self.subtitle_language:
            self.subtitle_language = 'zh-Hant'

        self.language_list = tuple([
            language for language in self.subtitle_language.split(',')])

    def get_territory(self):
        geo_url = self.api['geo'].format(bundle_id=urlparse(self.url).netloc)
        res = self.session.get(url=geo_url)
        if res.ok:
            data = res.json()
            if 'territory' in data:
                self.territory = data['territory']
                self.logger.debug(self.territory)
            else:
                self.logger.error(
                    self._("\nOut of service!"))
                sys.exit(0)
        else:
            self.logger.error(res.text)

    def login(self):

        if self.username and self.password:
            username = self.username
            password = self.password
        else:
            username = input(self._("HBOGO Asia username: "))
            password = getpass(self._("HBOGO Asia password: "))

        headers = {
            'origin': self.origin,
            'referer': self.origin
        }

        payload = {
            'contactPassword': password.strip(),
            'contactUserName': username.strip(),
            'deviceDetails': {
                'deviceName': platform.system(),
                'deviceType': "COMP",
                'modelNo': self.device_id,
                'serialNo': self.device_id,
                'appType': 'Web',
                'status': 'Active'
            }
        }

        auth_url = self.api['login']

        res = self.session.post(url=auth_url, headers=headers, json=payload)
        if res.ok:
            data = res.json()
            self.logger.debug(data)
            self.channel_partner_id = data['channelPartnerID']
            self.session_token = data['sessionToken']
            # self.multi_profile_id = response['multiProfileId']
            user_name = data['name']
            self.logger.info(
                self._("\nSuccessfully logged in. Welcome %s!"), user_name.strip())
        else:
            self.logger.error(res.text)
            sys.exit(1)

    def remove_device(self):
        delete_url = self.api['device']
        payload = {
            "sessionToken": self.session_token,
            "multiProfileId": "0",
            "serialNo": self.device_id
        }
        res = self.session.delete(url=delete_url, json=payload)
        if res.ok:
            self.logger.debug(res.json())
        else:
            self.logger.error(res.text)

    def get_all_languages(self, data):
        available_languages = tuple([self.get_language_code(
            media['lang']) for media in data['materials'] if media['type'] == 'subtitle'])

        if 'all' in self.language_list:
            self.language_list = available_languages

        if not set(self.language_list).intersection(set(available_languages)):
            self.logger.error(
                self._("\nSubtitle available languages: %s"), available_languages)
            sys.exit(0)

    def movie_subtitle(self, movie_url, content_id):
        res = self.session.get(url=movie_url)

        if res.ok:
            movie = res.json()

            title = next(title['name'] for title in movie['metadata']
                         ['titleInformations'] if title['lang'] == 'CHN').strip()
            release_year = movie['metadata']['releaseDate'][:4]

            self.logger.info("\n%s (%s)", title, release_year)
            title = self.ripprocess.rename_file_name(f'{title}.{release_year}')

            folder_path = os.path.join(self.download_path, title)

            if os.path.exists(folder_path):
                shutil.rmtree(folder_path)

            file_name = f'{title}.WEB-DL.{Platform.HBOGO}.vtt'

            self.logger.info(
                self._("\nDownload: %s\n---------------------------------------------------------------"), file_name)

            subtitles = self.get_subtitle(
                content_id, movie, folder_path, file_name)[0]

            self.download_subtitle(
                subtitles=subtitles, folder_path=folder_path)
        else:
            self.logger.error(res.text)

    def series_subtitle(self, series_url):
        res = self.session.get(url=series_url)
        if res.ok:
            season_list = res.json()['results']

            if len(season_list) > 0:
                if season_list[0]['metadata']['titleInformations'][-1]['lang'] != 'ENG':
                    title = season_list[0]['metadata']['titleInformations'][-1]['name']
                else:
                    title = season_list[0]['metadata']['titleInformations'][0]['name']
                title = re.sub(r'\(第\d+季\)', '', title).strip()
            else:
                self.logger.info(
                    self._("\nThe series isn't available in this region."))

            title = re.sub(r'S\d+', '', title).strip()
            self.logger.info(self._("\n%s total: %s season(s)"),
                             title, len(season_list))

            for season in season_list:
                season_index = int(season['seasonNumber'])
                if not self.download_season or season_index in self.download_season:
                    season_url = self.api['tvepisode'].format(
                        parent_id=season['contentId'], territory=self.territory)
                    self.logger.debug("season url: %s", season_url)

                    title = self.ripprocess.rename_file_name(
                        f'{title}.S{str(season_index).zfill(2)}')
                    folder_path = os.path.join(self.download_path, title)
                    if os.path.exists(folder_path):
                        shutil.rmtree(folder_path)

                    episode_res = self.session.get(url=season_url)
                    if episode_res.ok:
                        episode_list = episode_res.json()
                        episode_num = episode_list['total']

                        self.logger.info(
                            self._("\nSeason %s total: %s episode(s)\tdownload all episodes\n---------------------------------------------------------------"), season_index, episode_num)

                        languages = set()
                        subtitles = []
                        for episode in episode_list['results']:
                            episode_index = int(episode['episodeNumber'])
                            if not self.download_episode or episode_index in self.download_episode:
                                content_id = episode['contentId']

                                file_name = f'{title}E{str(episode_index).zfill(2)}.WEB-DL.{Platform.HBOGO}.vtt'

                                self.logger.info(
                                    self._("Finding %s ..."), file_name)
                                subs, lang_paths = self.get_subtitle(
                                    content_id, episode, folder_path, file_name)
                                subtitles += subs
                                languages = set.union(languages, lang_paths)

                        self.download_subtitle(
                            subtitles=subtitles, languages=languages, folder_path=folder_path)
        else:
            self.logger.error(res.text)

    def get_subtitle(self, content_id, data, folder_path, file_name):
        playback_url = self.api['playback'].format(territory=self.territory, content_id=content_id,
                                                   session_token=self.session_token, channel_partner_id=self.channel_partner_id)
        self.logger.debug(playback_url)
        res = self.session.get(url=playback_url)

        if res.ok:
            mpd_url = res.json()['playbackURL']

            category = data['metadata']['categories'][0]

            self.get_all_languages(data)

            lang_paths = set()
            subtitles = []
            for media in data['materials']:
                if media['type'] == 'subtitle':
                    self.logger.debug(media)
                    sub_lang = self.get_language_code(media['lang'])
                    if sub_lang in self.language_list:
                        if len(self.language_list) > 1:
                            if category == 'SERIES':
                                lang_folder_path = os.path.join(
                                    folder_path, sub_lang)
                            else:
                                lang_folder_path = folder_path
                        else:
                            lang_folder_path = folder_path
                        lang_paths.add(lang_folder_path)
                        subtitle_file = media['href']
                        lang_code = Path(
                            subtitle_file).stem.replace(content_id, '')

                        subtitle_file_name = file_name.replace(
                            '.vtt', f'.{sub_lang}.vtt')

                        subtitle_link = mpd_url.replace(
                            os.path.basename(mpd_url), f'subtitles/{lang_code}/{subtitle_file}')
                        self.logger.debug(subtitle_link)

                        os.makedirs(lang_folder_path,
                                    exist_ok=True)
                        subtitle = dict()
                        subtitle['name'] = subtitle_file_name
                        subtitle['path'] = lang_folder_path
                        subtitle['url'] = subtitle_link
                        subtitles.append(subtitle)
            return subtitles, lang_paths
        else:
            self.logger.error(res.text)
            sys.exit(1)

    def download_subtitle(self, subtitles, folder_path, languages=None):
        if subtitles:
            download_files(subtitles)
            if languages:
                for lang_path in sorted(languages):
                    convert_subtitle(
                        folder_path=lang_path, lang=self.locale)
            convert_subtitle(folder_path=folder_path,
                             platform=Platform.HBOGO, lang=self.locale)
            if self.output:
                shutil.move(folder_path, self.output)

    def main(self):
        self.origin = f"https://{urlparse(self.url).netloc}"

        self.get_language_list()
        self.get_territory()

        # nowe
        # driver = driver_init(False)
        # nowe_login = 'https://signin.nowe.com/ottidform/landing?lang=zh&template=HBO&redirect=https%3A%2F%2Fsaml.nowe.com%2Fidp_hbo%2Fgenerateresponseprepareforlogin%3Frequest_id%3DbKj2m8rsSyTAvkvjI5kUUGAw39nHhdv4sswc%21KjMADv9OtAMTtAapFss9qcjIcnn%26request_issuer%3DkOtAqX%21uHX0PC%212zarYbeWxtT4E-XWJzM90VvcgjJ3qTVvCv65FB2nEAVkP7Bg69%26request_issuerTime%3DoK1CXyT-lKroIfEUjA5EOg..%26RelayState%3DW-dZed54pHrrTr9jXdq6Fni6z6MVm9vZwEmEmXeDJsw.'
        # driver.get(nowe_login)
        # email = self.username
        # password = self.password

        # wait = WebDriverWait(driver, 10)
        # wait.until(EC.visibility_of_element_located(
        #     (By.ID, "psdInput"))).send_keys(email)

        # wait.until(EC.element_to_be_clickable(
        #     (By.ID, "confirmBtn"))).click()

        # wait.until(EC.visibility_of_element_located(
        #     (By.ID, "psdInput"))).send_keys(password)

        # wait.until(EC.element_to_be_clickable(
        #     (By.ID, "confirmBtn"))).click()
        # driver.quit()

        self.login()
        if '/sr' in self.url:
            series_id_regex = re.search(
                r'https:\/\/www\.hbogoasia.+\/sr(\d+)', self.url)
            if series_id_regex:
                series_id = series_id_regex.group(1)
                series_url = self.api['tvseason'].format(
                    parent_id=series_id, territory=self.territory)
                self.series_subtitle(series_url)
            else:
                self.logger.error(self._("\nSeries not found!"))
                sys.exit(1)
        else:
            content_id = os.path.basename(self.url)
            movie_url = self.api['movie'].format(
                content_id=content_id, territory=self.territory)
            self.movie_subtitle(movie_url=movie_url, content_id=content_id)
        self.remove_device()
