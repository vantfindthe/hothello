from hothello.scraper import clean_art, parse_artworks, parse_catalog

BROWSE = """
<div class="tree"><ul>
  <li class="grouping" data-grouping-id="1">
    <span class="grouping-label">Animals <span class="category-count">(20)</span> <a href="grouping.php?grouping_id=1">view all</a></span>
    <ul class="category-list">
      <li class="category category-item"><div class="browse-item-row">
        <input type="checkbox" class="browse-cb category-cb" data-id="12">
        <a href="cat.php?category_id=12" onclick="x(event, this.href)">
            Aardvarks          <span class="category-count">(4)</span></a></div></li>
      <li class="category category-item"><div class="browse-item-row">
        <a href="cat.php?category_id=46">Food &amp; Drink <span class="category-count">(16)</span></a></div></li>
    </ul>
  </li>
  <li class="grouping" data-grouping-id="2">
    <span class="grouping-label">Things <span class="category-count">(3)</span></span>
    <ul class="category-list">
      <li><a href="cat.php?category_id=99">Boxes <span class="category-count">(3)</span></a></li>
      <li><a href="cat.php?category_id=12">Aardvarks <span class="category-count">(4)</span></a></li>
    </ul>
  </li>
</ul></div>
<div class="tags-section"><a href="tag.php?tag_id=3">Animal</a> <span class="category-count">(9)</span></div>
"""

CATEGORY_PAGE = """
<div class="artwork-list" id="artwork-list">
<div class="adu-artwork-display" id="artwork-101" data-artwork="{&quot;id&quot;:101,&quot;height&quot;:3,&quot;width&quot;:9}" data-nudity="0" data-explicit="0">
    <h3><a href="https://asciiart.website/art/101">Tiny &amp; Box</a></h3>
    <div class="artwork-content"><div class="adu-artwork-container"><a href="https://asciiart.website/art/101">
            <pre class="adu-artwork-pre adu-dark-on-light "
                 id="artwork-pre-101" data-artwork-id="101" role="img"
                 aria-label="ASCII art depicting a box. Boxes."
                 style="font-size: 6.91px !important;"
            >    +--+
    |&lt;&gt;|   \t
    +--+ zz</pre></a></div></div>
    <div class="adu-artwork-metadata">
        <p><strong>Categories:</strong> <a href="cat.php?category_id=99">Boxes</a> | <a href="cat.php?category_id=12">Aardvarks</a></p>
        <p><strong>Tags:</strong> <a href="tag.php?tag_id=1">Box</a> | <a href="tag.php?tag_id=2">Square</a></p>
        <p><strong>Artist:</strong> <a href="artist.php?artist_id=5">zz</a></p>
    </div>
</div><!-- .adu-artwork-display --><div class="adu-artwork-display" id="artwork-102" data-artwork="{}" data-nudity="1" data-explicit="0">
    <h3><a href="https://asciiart.website/art/102">Flagged</a></h3>
    <pre class="adu-artwork-pre">x
y</pre>
    <p><strong>Categories:</strong> <a href="cat.php?category_id=99">Boxes</a></p>
    <p><strong>Artist:</strong> </p>
</div><!-- .adu-artwork-display --><div class="adu-artwork-display" id="artwork-103" data-nudity="0" data-explicit="0">
    <h3><a href="/art/103">Empty</a></h3>
    <pre class="adu-artwork-pre">   </pre>
</div><!-- .adu-artwork-display -->
<script>var x = "<strong>Artist:</strong> not me</p>";</script>
"""


def test_parse_catalog_keeps_every_membership():
    groupings, categories = parse_catalog(BROWSE)
    assert groupings == [(1, "Animals", 20), (2, "Things", 3)]
    assert (12, 1, "Aardvarks", 4) in categories
    assert (46, 1, "Food & Drink", 16) in categories
    assert (12, 2, "Aardvarks", 4) in categories  # listed under two groups
    assert all(c[0] != 3 for c in categories)  # tag links are not categories


def test_parse_artworks_fields():
    pieces = parse_artworks(CATEGORY_PAGE)
    assert [p.id for p in pieces] == [101, 102]  # the blank one is skipped
    box = pieces[0]
    assert box.title == "Tiny & Box"
    assert box.artist == "zz"
    assert box.text == "+--+\n|<>|\n+--+ zz"  # unescaped, dedented, trailing space gone
    assert (box.width, box.height) == (7, 3)
    assert box.categories == [(99, "Boxes"), (12, "Aardvarks")]
    assert box.tags == ["Box", "Square"]
    assert not box.flagged
    assert pieces[1].flagged
    assert pieces[1].artist == ""


def test_clean_art_strips_controls_and_tabs():
    raw = "\n\n  a\tb\x1b[31m\r\n  c\x07  \n\n"
    # tab stops count from the original line start (before dedenting); ESC is dropped
    assert clean_art(raw) == "a     b[31m\nc"


def test_clean_art_keeps_relative_indent():
    assert clean_art("    x\n  y\n      z") == "  x\ny\n    z"
