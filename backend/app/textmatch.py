"""Matching words the way a search box should: without accents or capitals, with typos, while typing."""
import re
import unicodedata


def fold(text):
    """'Amélie Poulain!' -> 'amelie poulain': lower case, no accents, anything that is not a letter or a digit is a space."""
    plain = unicodedata.normalize("NFKD", text or "")
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", plain.lower().replace("œ", "oe").replace("æ", "ae")).strip()


def tokens(text):
    return fold(text).split()


def distance(a, b):
    """Edits (insert, delete, replace, swap two neighbours) to turn a into b."""
    rows = [list(range(len(b) + 1))]
    for i, ca in enumerate(a, 1):
        row = [i]
        for j, cb in enumerate(b, 1):
            cost = min(rows[-1][j] + 1, row[j - 1] + 1, rows[-1][j - 1] + (ca != cb))
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cost = min(cost, rows[-2][j - 2] + 1)  # a swap: "chaplni" is one slip away from "chaplin"
            row.append(cost)
        rows.append(row)
    return rows[-1][-1]


def allowed_typos(length):
    # a short word with a typo is another word (cat, car): exact. Longer words forgive one slip, long ones two.
    return 0 if length < 4 else 1 if length < 8 else 2


EXACT, PREFIX, TYPO = 4, 3, 1


def word_quality(token, word):
    """How well one typed word matches one word of the text: EXACT, PREFIX (still being typed), TYPO, or 0."""
    if token == word:
        return EXACT
    if len(token) >= 3 and word.startswith(token):
        return PREFIX
    k = allowed_typos(len(token))
    if k and abs(len(token) - len(word)) <= k and distance(token, word) <= k:
        return TYPO
    return 0


def match_quality(query_tokens, words):
    """Every typed word must match a word of the text; the worst of them says how good the match is (0: no match)."""
    if not query_tokens or not words:
        return 0
    worst = EXACT
    for token in query_tokens:
        best = max(word_quality(token, w) for w in words)
        if best == 0:
            return 0
        worst = min(worst, best)
    return worst
