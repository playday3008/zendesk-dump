from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path

import os
import logging
import datetime
import base64
import json

from dotenv import load_dotenv
from werkzeug.utils import secure_filename

import requests
from requests.auth import HTTPBasicAuth

from dataclass_wizard import JSONWizard  # type: ignore

from bs4 import BeautifulSoup
import markdownify  # type: ignore


@dataclass
class Response(JSONWizard):
    count: int | None = None
    next_page: str | None = None
    page: int | None = None
    page_count: int | None = None
    per_page: int | None = None
    previous_page: str | None = None
    sort_by: str | None = None
    sort_order: str | None = None


@dataclass
class PageableObject:
    pass


@dataclass
class ArticleObject(PageableObject, JSONWizard):
    id: int
    url: str
    html_url: str
    author_id: int
    comments_disabled: bool
    draft: bool
    promoted: bool
    position: int
    vote_sum: int
    vote_count: int
    section_id: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    name: str
    title: str
    source_locale: str
    locale: str
    outdated: bool
    outdated_locales: list[str]
    edited_at: datetime.datetime
    user_segment_id: int | None
    permission_group_id: int
    content_tag_ids: list[str]
    label_names: list[str]
    body: str  # HTML
    user_segment_ids: list[int]

    def __hash__(self) -> int:
        return self.id


@dataclass
class ArticleAttachmentObject(PageableObject, JSONWizard):
    id: int
    url: str
    article_id: int
    display_file_name: str
    file_name: str
    locale: str | None
    content_url: str
    relative_path: str
    content_type: str  # mimetype
    size: int
    inline: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
    content_: str | None = None  # base64 encoded attachment, not in JSON


@dataclass
class CategoryObject(PageableObject, JSONWizard):
    id: int
    url: str
    html_url: str
    position: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    name: str
    description: str
    locale: str
    source_locale: str
    outdated: bool


@dataclass
class SectionObject(PageableObject, JSONWizard):
    id: int
    url: str
    html_url: str
    category_id: int
    position: int
    sorting: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    name: str
    description: str | None
    locale: str
    source_locale: str
    outdated: bool
    parent_section_id: int | None
    theme_template: str


@dataclass
class ArticlesResponse(Response, JSONWizard):
    articles: list[ArticleObject] = field(default_factory=list)


@dataclass
class ArticleAttachmentResponse(Response, JSONWizard):
    article_attachment: ArticleAttachmentObject | None = None


@dataclass
class ArticleAttachmentsResponse(Response, JSONWizard):
    article_attachments: list[ArticleAttachmentObject] = field(default_factory=list)


@dataclass
class CategoriesResponse(Response, JSONWizard):
    categories: list[CategoryObject] = field(default_factory=list)


@dataclass
class LocalesResponse(JSONWizard):
    locales: list[str]
    default_locale: str


@dataclass
class SectionsResponse(Response, JSONWizard):
    sections: list[SectionObject] = field(default_factory=list)


# Load environment variables from .env file (if present)
load_dotenv()

# Define environment variables (will raise error if not present)
LOG_LEVEL: str = os.getenv(key="LOG_LEVEL", default="DEBUG")
ZENDESK_DOMAIN: str = os.environ["ZENDESK_DOMAIN"]
ZENDESK_EMAIL: str = os.environ["ZENDESK_EMAIL"]
ZENDESK_API_TOKEN: str = os.environ["ZENDESK_API_TOKEN"]
ZENDESK_LOCALES: LocalesResponse = LocalesResponse(
    locales=os.getenv(key="ZENDESK_LOCALES", default="en-us").split(","),
    default_locale=os.getenv(key="ZENDESK_DEFAULT_LOCALE", default="en-us"),
)

# Start logging
logging.basicConfig(
    filemode=f"{Path(__file__).stem}.log",
    format="%(asctime)s (%(levelname)s): %(message)s",
)
logging.getLogger().setLevel(LOG_LEVEL)
# Log to stdout as well
# logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))

# Define global variables
articles: dict[str, list[ArticleObject]] = {}
articles_attachments: dict[int, list[ArticleAttachmentObject]] = {}
categories: dict[str, list[CategoryObject]] = {}
sections: dict[str, list[SectionObject]] = {}


def for_all_pages(
    session: requests.Session, endpoint: str
) -> list[type[PageableObject]]:
    objects: list[type[PageableObject]] = []
    while True:
        response: requests.Response = session.get(endpoint)
        if response.reason != "OK":
            logging.error(
                f"Failed to retrieve objects: {response.status_code} ({response.reason})"
            )
            raise RuntimeError

        # Get raw json
        json: dict[str, Any] = response.json()
        key_name: str = ""

        # Depending on available keys, determine the type of response
        data: Response
        if "articles" in json:
            data = ArticlesResponse.from_dict(json)
            key_name = "articles"
        elif "categories" in json:
            data = CategoriesResponse.from_dict(json)
            key_name = "categories"
        elif "sections" in json:
            data = SectionsResponse.from_dict(json)
            key_name = "sections"
        elif "article_attachments" in json:
            data = ArticleAttachmentsResponse.from_dict(json)
            key_name = "article_attachments"
        else:
            logging.error(f"Unknown response type: {json}")
            raise RuntimeError

        # Append the objects to the list
        objects.extend(getattr(data, key_name))

        # Check if there are more pages
        if data.next_page:
            endpoint = data.next_page
        else:
            break
    return objects


def get_session(email: str, token: str) -> requests.Session:
    session: requests.Session = requests.Session()
    session.auth = HTTPBasicAuth(f"{email}/token", token)
    return session


def get_locales(session: requests.Session) -> LocalesResponse:
    response: requests.Response = session.get(
        url=f"{ZENDESK_DOMAIN}/api/v2/help_center/locales",
        headers={"Accept": "application/json"},
    )
    if response.reason != "OK":
        logging.warning(
            f"Failed to retrieve supported locales: {response.status_code} ({response.reason}), using default: {ZENDESK_LOCALES.locales}"
        )
        return ZENDESK_LOCALES
    else:
        return LocalesResponse.from_dict(response.json())


def get_backup_path() -> Path:
    date: datetime.datetime = datetime.datetime.today()
    backup_path: Path = Path("backups") / secure_filename(str(date))
    backup_path.mkdir(parents=True, exist_ok=True)
    return backup_path


def download_all_resources(session: requests.Session):
    # Get the articles
    logging.info("Retrieving articles...")
    for locale in ZENDESK_LOCALES.locales:
        articles[locale] = for_all_pages(  # type: ignore
            session=session,
            endpoint=f"{ZENDESK_DOMAIN}/api/v2/help_center/{locale}/articles?per_page=100",
        )

    logging.info(
        f"Articles count: {format(sum(len(articles[locale]) for locale in articles), ',')}"
    )
    # logging.debug(f"Articles: {articles}")

    # Get the attachments
    logging.info("Retrieving attachments...")
    distinct_articles: list[ArticleObject] = list(set().union(*articles.values()))  # type: ignore
    for article in distinct_articles:
        # Do not believe the attachments API, parse HTML and extract attachments

        if article.id not in articles_attachments:
            articles_attachments[article.id] = []
        soup = BeautifulSoup(article.body, "html.parser")
        for img in soup.find_all("img"):
            response: requests.Response
            try:
                attachment_id = int(
                    img["src"].split("article_attachments/")[1].split("/")[0]
                )
                response: requests.Response = session.get(
                    f"{ZENDESK_DOMAIN}/api/v2/help_center/articles/{article.id}/attachments/{attachment_id}"
                )
            except:
                logging.warning(f"Non-zendesk attachment found ({img["src"]}), skipping...")
                continue
            if response.reason != "OK":
                logging.error(
                    f"Failed to retrieve attachment: {response.status_code} ({response.reason})"
                )
                raise RuntimeError
            attachment = ArticleAttachmentResponse.from_dict(response.json())
            if attachment.article_attachment:
                articles_attachments[article.id].append(attachment.article_attachment)

        # articles_attachments[article.id] = for_all_pages(  # type: ignore
        #    session=session,
        #    endpoint=f"{ZENDESK_DOMAIN}/api/v2/help_center/articles/{article.id}/attachments?per_page=100",
        # )

        # Download an attachment into ArticleObject.content_
        for attachment in articles_attachments[article.id]:
            attachment.content_ = base64.b64encode(
                session.get(attachment.content_url).content
            ).decode("utf-8")

    logging.info(
        f"Attachments count: {format(sum(len(articles_attachments[article.id]) for article in distinct_articles), ',')}"
    )
    # logging.debug(f"Attachments: {articles_attachments}")

    # Get the categories
    logging.info("Retrieving categories...")
    for locale in ZENDESK_LOCALES.locales:
        categories[locale] = for_all_pages(  # type: ignore
            session=session,
            endpoint=f"{ZENDESK_DOMAIN}/api/v2/help_center/{locale}/categories?per_page=100",
        )

    logging.info(
        f"Categories count: {format(sum(len(categories[locale]) for locale in categories), ',')}"
    )
    # logging.debug(f"Categories: {categories}")

    # Get the sections
    logging.info("Retrieving sections...")
    for locale in ZENDESK_LOCALES.locales:
        sections[locale] = for_all_pages(  # type: ignore
            session=session,
            endpoint=f"{ZENDESK_DOMAIN}/api/v2/help_center/{locale}/sections?per_page=100",
        )

    logging.info(
        f"Sections count: {format(sum(len(sections[locale]) for locale in sections), ',')}"
    )
    # logging.debug(f"Sections: {sections}")


def save_raw_data_to_disk(backup_path: Path):
    # Create folders
    backup_path = backup_path / Path("raw")
    backup_path.mkdir(parents=True, exist_ok=True)
    (backup_path / "articles").mkdir(parents=True, exist_ok=True)
    (backup_path / "categories").mkdir(parents=True, exist_ok=True)
    (backup_path / "sections").mkdir(parents=True, exist_ok=True)

    # Save raw data to disk as JSON
    for locale in ZENDESK_LOCALES.locales:
        with open(backup_path / "articles" / f"articles_{locale}.json", "w") as file:
            file.write(
                f"{json.dumps({'articles': [ArticleObject.to_dict(article) for article in articles[locale]]}, default=str, indent=4)}\n"
            )

        with open(
            backup_path / "categories" / f"categories_{locale}.json", "w"
        ) as file:
            file.write(
                f"{json.dumps({'categories': [CategoryObject.to_dict(category) for category in categories[locale]]}, default=str, indent=4)}\n"
            )

        with open(backup_path / "sections" / f"sections_{locale}.json", "w") as file:
            file.write(
                f"{json.dumps({'sections': [SectionObject.to_dict(section) for section in sections[locale]]}, default=str, indent=4)}\n"
            )

    with open(backup_path / f"articles_attachments.json", "w") as file:
        attachments = [
            ArticleAttachmentObject.to_dict(attachment)
            for attachments in articles_attachments.values()
            for attachment in attachments
        ]
        file.write(
            f"{json.dumps({'articles_attachments': attachments}, default=str, indent=4)}\n"
        )


def save_nice_data_to_disk(backup_path: Path):
    """
    Save all data as a directory structure on disk with the following layout:
    - category_name/
        - section_name/
            - article_name/
                - attachments/
                    - attachment_name
                - article_name.md
                - article_name.html
    """

    for locale in ZENDESK_LOCALES.locales:
        for article in articles[locale]:
            # Get section and category for that article
            section: SectionObject = next(
                (x for x in sections[locale] if x.id == article.section_id)
            )
            category: CategoryObject = next(
                (x for x in categories[locale] if x.id == section.category_id)
            )

            # Define path for article
            path = backup_path / Path(secure_filename(category.name)) / Path(secure_filename(section.name))
            # Make forlder for it
            path.mkdir(parents=True, exist_ok=True)

            # Save all attachments
            attachments_path: Path = path / Path("attachments")
            attachments_path.mkdir(parents=True, exist_ok=True)
            for attachment in articles_attachments[article.id]:
                if not attachment.content_:
                    raise RuntimeError
                attachment_path: Path = attachments_path / str(attachment.id)
                attachment_path.mkdir(parents=True, exist_ok=True)
                with open(attachment_path / secure_filename(attachment.display_file_name), "wb") as file:
                    file.write(base64.b64decode(attachment.content_))

            # Modify the article body to have local paths
            soup = BeautifulSoup(article.body, "html.parser")

            # Replace all src in img tags to local files
            imgs = soup.find_all("img")
            img_urls = [img["src"] for img in imgs]
            for img, img_url in zip(imgs, img_urls):
                attachment_id: int
                try:
                    # Find url with `article_attachments` in it, and get the attachment id after it
                    attachment_id = int(
                        img_url.split("article_attachments/")[1].split("/")[0]
                    )
                except:
                    logging.warning(f"Non-zendesk attachment found ({img_url}), skipping...")
                    continue
                # Replace the src with the local path
                attachment_name: str = ""
                try:
                    attachment_name = next(
                        attachment.display_file_name
                        for _article in articles[locale]
                        for attachment in articles_attachments[_article.id]
                        if attachment.id == attachment_id
                    )
                except StopIteration:
                    logging.error(f"Attachment not found: {attachment_id}")
                    raise RuntimeError
                img["src"] = f"./attachments/{attachment_id}/{attachment_name}"

            # Render html
            article.body = str(soup)

            # Sane filename
            article.title = secure_filename(article.title)

            # Save as markdown
            with open(path / f"{article.title}.md", "w") as file:
                file.write(markdownify.markdownify(article.body))  # type: ignore

            # Save as html
            with open(path / f"{article.title}.html", "w") as file:
                file.write(article.body)


def main():
    # Define session
    logging.info("Creating session...")
    session = get_session(ZENDESK_EMAIL, ZENDESK_API_TOKEN)
    logging.info(f"Session created with email: {ZENDESK_EMAIL}")

    # Get list of supported locales
    logging.info("Retrieving supported locales...")
    global ZENDESK_LOCALES
    ZENDESK_LOCALES = get_locales(session)  # type: ignore
    logging.info(f"Supported locales: {ZENDESK_LOCALES.locales}")

    # Create backup directory
    logging.info("Creating backup directory...")
    backup_path: Path = get_backup_path()
    logging.info(f"Backup directory: {backup_path}")

    # Download all resources
    logging.info("Downloading all resources...")
    download_all_resources(session)
    logging.info("All resources downloaded")

    # Save raw data to disk (JSON)
    logging.info("Saving raw data to disk...")
    save_raw_data_to_disk(backup_path)
    logging.info("Raw data saved")

    # Save nice data to disk (Markdown and HTML)
    logging.info("Saving nice data to disk...")
    save_nice_data_to_disk(backup_path)
    logging.info("Nice data saved")


if __name__ == "__main__":
    main()
