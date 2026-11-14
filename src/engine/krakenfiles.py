#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - krakenfiles.py
# Modified 2026 by megabitus98 (fork): English texts from config.constant, failures raise to the handler, which replies once

__author__ = "SanujaNS <sanujas@sanuja.biz>"

import logging

import requests
from bs4 import BeautifulSoup
from config import BotText
from engine.direct import DirectDownload


def krakenfiles_download(client, bot_message, url: str):
    session = requests.Session()

    def _extract_form_data(url: str) -> list[tuple[str, str]]:
        try:
            resp = session.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.content, "html.parser")

            if post_url := soup.xpath('//form[@id="dl-form"]/@action'):
                post_url = f"https://krakenfiles.com{post_url[0]}"
            else:
                raise ValueError("ERROR: Unable to find post link.")
            if token := soup.xpath('//input[@id="dl-token"]/@value'):
                data = {"token": token[0]}
            else:
                raise ValueError("ERROR: Unable to find token for post.")

            return list(zip(post_url, data))

        except requests.RequestException as e:
            raise ValueError(f"Failed to fetch page: {str(e)}")
        except Exception as e:
            raise ValueError(f"Failed to parse page: {str(e)}")

    def _get_download_url(form_data: list[tuple[str, str]]) -> str:
        for post_url, data in form_data:
            try:
                response = session.post(post_url, data=data)
                response.raise_for_status()

                json_data = response.json()
                if "url" in json_data:
                    return json_data["url"]

            except (requests.RequestException, ValueError):
                logging.exception("Krakenfiles form submission failed")

        raise ValueError("Could not obtain download URL")

    def _download(url: str):
        bot_message.edit_text(BotText.krakenfiles_start)
        form_data = _extract_form_data(url)
        download_url = _get_download_url(form_data)

        bot_message.edit_text(BotText.downloading)
        downloader = DirectDownload(client, bot_message, download_url)
        downloader.start()

    _download(url)
