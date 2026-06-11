import html
import logging
import re
from typing import Any
from urllib.parse import urljoin

import requests


logger = logging.getLogger(__name__)


class BiletinialScraper:
    BASE_URL = "https://biletinial.com"
    CITY_ID = 147
    CITY_URL = "istanbul"
    LIST_URL = f"{BASE_URL}/tr-tr/sinema/{CITY_URL}"
    CDN_BASE_URL = "https://b6s54eznn8xq.merlincdn.net"

    def __init__(
        self,
        max_movies: int = 80,
        comments_per_movie: int = 5,
        max_seance_dates: int = 3,
    ) -> None:
        self.max_movies = max_movies
        self.comments_per_movie = comments_per_movie
        self.max_seance_dates = max_seance_dates
        self._venue_cache: dict[str, dict[str, Any]] = {}
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
                ),
                "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
            }
        )

    @staticmethod
    def _clean_text(value: str) -> str:
        value = re.sub(r"<[^>]+>", " ", value)
        value = html.unescape(value)
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _parse_float(value: str) -> float:
        cleaned = value.strip().replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    @staticmethod
    def _parse_int(value: str) -> int:
        digits = re.sub(r"\D+", "", value)
        return int(digits) if digits else 0

    def _get_html(self, url: str) -> str:
        response = self.session.get(url, timeout=20)
        response.raise_for_status()
        return response.text

    def _absolute_image_url(self, image_url: str) -> str:
        if not image_url:
            return ""
        if image_url.startswith("http"):
            return image_url
        return f"{self.CDN_BASE_URL}{image_url}"

    def _parse_list_page(self, page_html: str) -> list[dict[str, Any]]:
        container_match = re.search(
            r'<ul[^>]+id="eventListContainer"[^>]*>(.*?)</ul>',
            page_html,
            flags=re.S,
        )
        if not container_match:
            return []

        cards = re.findall(r"<li>\s*(.*?)</li>", container_match.group(1), flags=re.S)
        movies: list[dict[str, Any]] = []
        for index, card in enumerate(cards[: self.max_movies], start=1):
            link_match = re.search(r'<h3>\s*<a[^>]+href="([^"]+)"[^>]+title="([^"]+)"', card)
            if not link_match:
                continue

            image_match = re.search(r"<img[^>]+src=\"([^\"]+)\"", card)
            rating_match = re.search(r"<strong>.*?</strong>\s*<span>\((.*?)\s+Yorum\)</span>", card, flags=re.S)
            score_match = re.search(r"<strong>.*?<img[^>]*>\s*([^<]+)", card, flags=re.S)
            address_match = re.search(r"<address>\s*<b>(.*?)</b>\s*<small>(.*?)</small>", card, flags=re.S)
            date_match = re.search(r"<address>.*?</address>\s*<span>(.*?)</span>", card, flags=re.S)

            detail_url = urljoin(self.BASE_URL, html.unescape(link_match.group(1)))
            poster_url = self._absolute_image_url(html.unescape(image_match.group(1)) if image_match else "")
            title = self._clean_text(link_match.group(2))
            city = self._clean_text(address_match.group(1)) if address_match else ""
            venue = self._clean_text(address_match.group(2)) if address_match else ""
            show_dates = self._clean_text(date_match.group(1)) if date_match else ""

            movies.append(
                {
                    "rank": index,
                    "title": title,
                    "detail_url": detail_url,
                    "poster_path": poster_url,
                    "biletinial_rating": self._parse_float(score_match.group(1)) if score_match else 0.0,
                    "biletinial_comment_count": self._parse_int(rating_match.group(1)) if rating_match else 0,
                    "city": city,
                    "venue": venue,
                    "show_dates": show_dates,
                    "playing_at": [
                        {
                            "city": city,
                            "cinema": venue,
                            "source": "listing",
                            "dates": [show_dates] if show_dates else [],
                        }
                    ] if venue else [],
                }
            )

        return movies

    def _fetch_more_list_items(self) -> list[dict[str, Any]]:
        movies: list[dict[str, Any]] = []
        page = 1
        while len(movies) < self.max_movies:
            response = self.session.get(
                f"{self.BASE_URL}/List/GetMoreItems",
                params={
                    "region": "tr-tr",
                    "cityId": self.CITY_ID,
                    "cityUrl": self.CITY_URL,
                    "order": 0,
                    "isKids": "false",
                    "isCampaign": "false",
                    "isForeign": "false",
                    "organizerUrl": "sinema",
                    "page": page,
                },
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
            items = data.get("items", [])
            for item in items:
                seo_url = item.get("seoUrl", "")
                if not seo_url:
                    continue
                seances = item.get("seances") or item.get("Seances") or []
                city = self._clean_text(str(item.get("cityName") or "İstanbul"))
                venue = self._clean_text(str(item.get("saloonName") or ""))
                movies.append(
                    {
                        "rank": len(movies) + 51,
                        "title": self._clean_text(str(item.get("name") or "")),
                        "detail_url": f"{self.BASE_URL}/tr-tr/sinema/{seo_url}",
                        "poster_path": self._absolute_image_url(str(item.get("imageUrl") or "")),
                        "biletinial_rating": self._parse_float(str(item.get("avgRate") or "")),
                        "biletinial_comment_count": int(item.get("commentCount") or 0),
                        "city": city,
                        "venue": venue,
                        "show_dates": ", ".join(seances),
                        "playing_at": [
                            {
                                "city": city,
                                "cinema": venue,
                                "source": "listing",
                                "seances": seances,
                            }
                        ] if venue else [],
                    }
                )
            if not data.get("hasMore") or not items:
                break
            page += 1
        return movies

    def _fetch_comments(self, film_id: str, referer: str) -> list[dict[str, Any]]:
        if not film_id or self.comments_per_movie <= 0:
            return []

        response = self.session.post(
            f"{self.BASE_URL}/tr-tr/Details/GetFilmComments",
            json={
                "filmId": film_id,
                "pageNumber": 1,
                "pageSize": self.comments_per_movie,
                "sortType": 1,
                "cinemaBranchs": [],
            },
            headers={"Referer": referer},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        comments = []
        for item in data.get("Comments", [])[: self.comments_per_movie]:
            detail = self._clean_text(str(item.get("Detail") or ""))
            if not detail:
                continue
            comments.append(
                {
                    "author": self._clean_text(
                        f"{item.get('Name', '')} {str(item.get('LastName') or '')[:1]}."
                    ),
                    "content": detail,
                    "rating": item.get("Rate"),
                    "created_at": item.get("StringDate", ""),
                    "venue": item.get("Branch", ""),
                    "did_watch": item.get("DidWatch", False),
                    "is_spoiler": item.get("IsSpoiler", False),
                }
            )
        return comments

    def _fetch_available_seance_dates(self, event_id: str) -> list[str]:
        response = self.session.get(
            f"{self.BASE_URL}/details/GetDateListForCity",
            params={"eventId": event_id, "langId": 1, "cityId": self.CITY_ID},
            timeout=20,
        )
        response.raise_for_status()
        dates = re.findall(r'data-date="(\d{4}-\d{2}-\d{2})"', response.text)
        return dates[: self.max_seance_dates]

    def _fetch_venue_metadata(self, venue_url: str) -> dict[str, Any]:
        if not venue_url:
            return {}
        if venue_url in self._venue_cache:
            return self._venue_cache[venue_url]

        try:
            venue_html = self._get_html(venue_url)
        except requests.RequestException as exc:
            logger.warning("Biletinial venue fetch failed for %s: %s", venue_url, exc)
            self._venue_cache[venue_url] = {}
            return {}

        address_match = re.search(r"<h3>Adres</h3>\s*<p>(.*?)</p>", venue_html, flags=re.S)
        map_match = re.search(r"maps\.google\.com/maps\?q=([-\d.]+),([-\d.]+)", venue_html)
        metadata: dict[str, Any] = {
            "venue_url": venue_url,
            "address": self._clean_text(address_match.group(1)) if address_match else "",
        }
        if map_match:
            metadata["lat"] = float(map_match.group(1))
            metadata["lon"] = float(map_match.group(2))

        self._venue_cache[venue_url] = metadata
        return metadata

    def _parse_seance_html(self, seance_html: str, seance_date: str) -> list[dict[str, Any]]:
        venues: list[dict[str, Any]] = []
        blocks = re.findall(
            r'<div class="yn_cinema"[^>]*>(.*?)(?=<div class="yn_cinema"|<script>|$)',
            seance_html,
            flags=re.S,
        )
        for block in blocks:
            cinema_match = re.search(
                r'class="yn_cinema_info_titleh2"><a[^>]*>(?:<img[^>]*>)?([^<]+)</a>',
                block,
                flags=re.S,
            )
            venue_href_match = re.search(
                r'class="yn_cinema_info_titleh2"><a[^>]+href="([^"]+)"',
                block,
                flags=re.S,
            )
            date_match = re.search(r'class="yn_cinema_info_date">.*?<span>(.*?)</span>', block, flags=re.S)
            saloons = []
            saloon_blocks = re.findall(
                r'<div class="yn_cinema_salon_info">\s*(.*?)(?=<div class="yn_cinema_salon_info">|</div>\s*</div>\s*</div>|$)',
                block,
                flags=re.S,
            )
            for saloon_block in saloon_blocks:
                saloon_match = re.search(r"<h2>(.*?)</h2>", saloon_block, flags=re.S)
                format_match = re.search(r"<span>(.*?)</span>", saloon_block, flags=re.S)
                times = [
                    self._clean_text(time)
                    for time in re.findall(r"<button[^>]*>\s*([^<]+?)\s*</button>", saloon_block, flags=re.S)
                ]
                if saloon_match or times:
                    saloons.append(
                        {
                            "saloon": self._clean_text(saloon_match.group(1)) if saloon_match else "",
                            "format": self._clean_text(format_match.group(1)) if format_match else "",
                            "times": times,
                        }
                    )
            if cinema_match or saloons:
                venue_url = urljoin(self.BASE_URL, html.unescape(venue_href_match.group(1))) if venue_href_match else ""
                venue_metadata = self._fetch_venue_metadata(venue_url)
                venues.append(
                    {
                        "city": "İstanbul",
                        "cinema": self._clean_text(cinema_match.group(1)) if cinema_match else "",
                        "date": self._clean_text(date_match.group(1)) if date_match else seance_date,
                        "saloons": saloons,
                        "source": "seance",
                        **venue_metadata,
                    }
                )
        return venues

    def _fetch_playing_at(self, event_id: str) -> list[dict[str, Any]]:
        if not event_id:
            return []

        playing_at: list[dict[str, Any]] = []
        for seance_date in self._fetch_available_seance_dates(event_id):
            response = self.session.get(
                f"{self.BASE_URL}/dynamic/get_seances/{event_id}/{self.CITY_ID}/{seance_date}/1/tr",
                timeout=20,
            )
            response.raise_for_status()
            playing_at.extend(self._parse_seance_html(response.text, seance_date))
        return playing_at

    def _parse_audience_rating(self, detail_html: str) -> float:
        for block in re.findall(
            r'<div class="yds_cinema_details_rating">\s*(.*?)\s*</div>\s*</div>\s*</div>\s*</div>',
            detail_html,
            flags=re.S,
        ):
            if "İzleyici Puanı" not in block:
                continue
            rating_match = re.search(
                r'class="yds_cinema_details_rating_point_number">\s*<p>(.*?)</p>',
                block,
                flags=re.S,
            )
            if rating_match:
                return self._parse_float(self._clean_text(rating_match.group(1)))
        rating_match = re.search(
            r'yds_cinema_details_rating_point_number">\s*<p>([\d,.-]+)</p>.*?İzleyici Puanı',
            detail_html,
            flags=re.S,
        )
        return self._parse_float(rating_match.group(1)) if rating_match else 0.0

    def _enrich_from_detail_page(self, movie: dict[str, Any]) -> dict[str, Any]:
        detail_html = self._get_html(movie["detail_url"])
        title_match = re.search(r"<h1>(.*?)</h1>", detail_html, flags=re.S)
        film_id_match = re.search(r"filmId:\s*'(\d+)'", detail_html)
        genres = [
            self._clean_text(match)
            for match in re.findall(r'class="yds_genres_link"[^>]*>(.*?)</a>', detail_html, flags=re.S)
        ]
        overview_match = re.search(
            r'<div class="yds_cinema_movie_thread_info">\s*(.*?)\s*</div>',
            detail_html,
            flags=re.S,
        )
        release_match = re.search(r"<strong>Vizyon Tarihi</strong>\s*<span[^>]*>(.*?)</span>", detail_html, flags=re.S)
        duration_match = re.search(r"<strong>Süre</strong>\s*<span[^>]*>(.*?)</span>", detail_html, flags=re.S)
        age_match = re.search(r"<strong>Yaş Sınırı</strong>\s*<span[^>]*>(.*?)</span>", detail_html, flags=re.S)
        director_match = re.search(r"Yönetmen:\s*<span[^>]*>\s*(.*?)</span>", detail_html, flags=re.S)
        audience_rating = self._parse_audience_rating(detail_html)
        comment_count_match = re.search(r'title="Tüm Yorumlar">([\d.]+)\s+Yorum', detail_html)

        film_id = film_id_match.group(1) if film_id_match else ""
        comments = self._fetch_comments(film_id, movie["detail_url"]) if film_id else []
        playing_at = self._fetch_playing_at(film_id) if film_id else []

        enriched = {
            **movie,
            "id": f"biletinial:{film_id or movie['rank']}",
            "source": "biletinial",
            "biletinial_id": film_id,
            "title": self._clean_text(title_match.group(1)) if title_match else movie["title"],
            "genre_names": genres,
            "genre_ids": [],
            "overview": self._clean_text(overview_match.group(1)) if overview_match else "",
            "release_date": self._clean_text(release_match.group(1)) if release_match else "",
            "duration": self._clean_text(duration_match.group(1)) if duration_match else "",
            "age_rating": self._clean_text(age_match.group(1)) if age_match else "",
            "director": self._clean_text(director_match.group(1)) if director_match else "",
            "original_language": "tr",
            "vote_average": movie.get("biletinial_rating") or 0.0,
            "vote_count": movie.get("biletinial_comment_count") or 0,
            "popularity": float(movie.get("biletinial_comment_count") or 0),
            "biletinial_comments": comments,
            "playing_at": playing_at or movie.get("playing_at", []),
        }
        if audience_rating:
            enriched["biletinial_rating"] = audience_rating
            enriched["vote_average"] = audience_rating
        if comment_count_match:
            enriched["biletinial_comment_count"] = self._parse_int(comment_count_match.group(1))
            enriched["vote_count"] = enriched["biletinial_comment_count"]
            enriched["popularity"] = float(enriched["biletinial_comment_count"])
        return enriched

    def run(self) -> dict[str, Any]:
        logger.info("BiletinialScraper started")
        page_html = self._get_html(self.LIST_URL)
        listed_movies = self._parse_list_page(page_html)
        seen_urls = {movie["detail_url"] for movie in listed_movies}
        if len(listed_movies) < self.max_movies:
            for movie in self._fetch_more_list_items():
                if movie["detail_url"] in seen_urls:
                    continue
                listed_movies.append(movie)
                seen_urls.add(movie["detail_url"])
                if len(listed_movies) >= self.max_movies:
                    break
        movies = []
        for movie in listed_movies:
            try:
                movies.append(self._enrich_from_detail_page(movie))
            except requests.RequestException as exc:
                logger.warning("Biletinial detail fetch failed for %s: %s", movie.get("title"), exc)
                movies.append({**movie, "source": "biletinial", "biletinial_comments": []})

        movies.sort(
            key=lambda movie: (
                int(movie.get("biletinial_comment_count") or 0),
                float(movie.get("biletinial_rating") or 0.0),
            ),
            reverse=True,
        )
        logger.info("BiletinialScraper completed: movies=%d", len(movies))
        return {
            "movies": movies,
            "metadata": {
                "source": "biletinial",
                "city": "İstanbul",
                "city_id": self.CITY_ID,
                "city_url": self.CITY_URL,
                "total_fetched": len(listed_movies),
                "total_after_filter": len(movies),
            },
        }
