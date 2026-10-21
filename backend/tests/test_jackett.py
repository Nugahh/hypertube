import asyncio

import pytest

from app import jackett

# Hand-written Torznab feed shaped like Jackett's real output: <link> is a Jackett
# proxy URL carrying the API key, the provider page lives in <comments>.
FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <title>Internet Archive</title>
    <item>
      <title>Sintel.2010.720p</title>
      <guid>https://archive.org/download/sintel/sintel_archive.torrent</guid>
      <jackettindexer id="internetarchive">Internet Archive</jackettindexer>
      <comments>https://archive.org/details/sintel</comments>
      <size>760000000</size>
      <link>http://jackett:9117/dl/internetarchive/?jackett_apikey=SECRETKEY&amp;path=abc&amp;file=Sintel</link>
      <enclosure url="http://jackett:9117/dl/internetarchive/?jackett_apikey=SECRETKEY&amp;path=abc" length="760000000" type="application/x-bittorrent" />
      <torznab:attr name="seeders" value="47" />
      <torznab:attr name="peers" value="50" />
    </item>
    <item>
      <title>Big Buck Bunny</title>
      <guid>https://archive.org/download/BigBuckBunny_124/BigBuckBunny_124_archive.torrent</guid>
      <jackettindexer id="internetarchive">Internet Archive</jackettindexer>
      <comments>https://archive.org/details/BigBuckBunny_124</comments>
      <size>1400000000</size>
      <link>http://jackett:9117/dl/internetarchive/?jackett_apikey=SECRETKEY&amp;path=def&amp;file=BBB</link>
      <torznab:attr name="seeders" value="52" />
      <torznab:attr name="peers" value="60" />
    </item>
    <item>
      <title>Old Silent Film</title>
      <guid>https://example.org/details/42</guid>
      <jackettindexer id="other">Other</jackettindexer>
      <comments>https://example.org/details/42</comments>
      <size>1000</size>
      <link>http://jackett:9117/dl/other/?jackett_apikey=SECRETKEY&amp;path=ghi</link>
    </item>
  </channel>
</rss>
"""

ERROR_FEED = '<?xml version="1.0" encoding="UTF-8"?><error code="100" description="Invalid API Key" />'


def test_results_are_sorted_most_seeded_first():
    titles = [r["title"] for r in jackett.parse_results(FEED)]
    assert titles == ["Big Buck Bunny", "Sintel.2010.720p", "Old Silent Film"]


def test_item_fields_are_normalized():
    sintel = jackett.parse_results(FEED)[1]
    assert sintel["id"] == "https://archive.org/download/sintel/sintel_archive.torrent"
    assert sintel["size"] == 760000000
    assert sintel["seeders"] == 47
    assert sintel["peers"] == 50
    assert sintel["provider"] == "Internet Archive"
    assert sintel["cover"] == "https://archive.org/services/img/sintel"
    assert sintel["link"].startswith("http://jackett:9117/dl/internetarchive/")


def test_missing_seeders_default_to_zero_and_unknown_cover_is_none():
    old = jackett.parse_results(FEED)[2]
    assert old["seeders"] == 0
    assert old["peers"] == 0
    assert old["cover"] is None


@pytest.mark.parametrize(
    "title, year, resolution",
    [
        ("Sintel.2010.720p.BluRay", 2010, "720p"),
        ("Big Buck Bunny", None, None),
        ("2001 A Space Odyssey 1968 1080p", 1968, "1080p"),
        ("Tears of Steel 2160p", None, "2160p"),
    ],
)
def test_year_and_resolution_come_from_the_title(title, year, resolution):
    assert jackett.parse_title(title) == (year, resolution)


def test_jackett_error_feed_raises():
    with pytest.raises(jackett.JackettError, match="Invalid API Key"):
        jackett.parse_results(ERROR_FEED)


def test_jackett_error_keeps_only_the_first_line_of_a_stack_trace():
    # real Jackett error 900: the description carries the whole .NET stack trace
    feed = (
        '<error code="900" description="Jackett.Common.IndexerException: Exception (internetarchive): '
        'Error Parsing Rows Selector.&#xA;   at Jackett.Common.Indexers.Definitions.CardigannIndexer.PerformQuery" />'
    )
    with pytest.raises(jackett.JackettError) as err:
        jackett.parse_results(feed)
    assert "Error Parsing Rows Selector" in str(err.value)
    assert "PerformQuery" not in str(err.value)


@pytest.mark.parametrize(
    "q, expected",
    [
        ("", "collection:feature_films"),
        ("   ", "collection:feature_films"),
        ("sintel", "sintel"),
        ("sintel (", "sintel"),  # an unbalanced "(" makes archive.org's query syntax fail
        ('sintel "open', "sintel open"),
        ("L'arrivée d'un train", "L'arrivée d'un train"),
        ("spider-man", "spider man"),
        ("title:sintel", "title sintel"),  # users cannot inject query syntax
    ],
)
def test_build_query_strips_query_syntax_and_defaults_to_popular_films(q, expected):
    assert jackett.build_query(q) == expected


@pytest.mark.parametrize(
    "q, genre, expected",
    [
        ("", "horreur", "collection:SciFi_Horror"),
        ("", "noir", 'collection:feature_films AND subject:"film noir"'),
        ("bunny", "animation", "(bunny) AND (collection:animationandcartoons)"),
        ("bunny", None, "bunny"),  # no genre: search every movie, not only the feature films
    ],
)
def test_build_query_combines_the_words_with_the_genre(q, genre, expected):
    assert jackett.build_query(q, genre) == expected


def test_every_genre_has_a_label_and_a_known_section():
    assert jackett.GENRES["populaires"]["section"] == "films"
    assert {g["section"] for g in jackett.GENRES.values()} == {"films", "series"}
    # the open-movies row is not an archive.org query: the second source answers it
    assert all(g["label"] and (g["query"] or key == "blender") for key, g in jackett.GENRES.items())


def test_search_sends_the_genre_to_jackett(monkeypatch):
    sent = []

    async def fetch(q):
        sent.append(q)
        return FEED

    monkeypatch.setattr(jackett, "fetch_xml", fetch)
    asyncio.run(jackett.search("", "horreur"))
    assert sent == ["collection:SciFi_Horror"]


def test_search_sends_the_cleaned_query_to_jackett(monkeypatch):
    sent = []

    async def fetch(q):
        sent.append(q)
        return FEED

    monkeypatch.setattr(jackett, "fetch_xml", fetch)
    asyncio.run(jackett.search("sintel ("))
    assert sent == ["sintel"]


def _search(monkeypatch, q):
    async def fetch(_):
        return FEED

    monkeypatch.setattr(jackett, "fetch_xml", fetch)
    return [r["title"] for r in asyncio.run(jackett.search(q))]


def test_search_drops_results_whose_title_misses_a_query_word(monkeypatch):
    # archive.org also matches descriptions: a "bunny" search must not return Sintel
    assert _search(monkeypatch, "bunny") == ["Big Buck Bunny"]
    assert _search(monkeypatch, "BUNNY big") == ["Big Buck Bunny"]
    assert _search(monkeypatch, "bunny sintel") == []


def test_search_results_are_sorted_by_name_but_the_home_page_keeps_popularity_order(monkeypatch):
    # the subject asks for name order after a search; "e" matches Sintel (47 seeders) and Old Silent Film (0)
    assert _search(monkeypatch, "e") == ["Old Silent Film", "Sintel.2010.720p"]
    assert _search(monkeypatch, "") == ["Big Buck Bunny", "Sintel.2010.720p", "Old Silent Film"]
