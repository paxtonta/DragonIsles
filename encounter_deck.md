# Hand-authored encounter deck

`data/encounters.json` is the shipped 50-card deck. It is an unofficial
reconstruction wired directly into the app; the values are not presented as a
transcription of the published game.

## Deck shape

- 10 Locations, 10 Oni, 10 Bakemono, 10 Tsukumogami, and 10 Dragons.
- 25 Land and 25 Sea encounters.
- Every Dragon is Sea and has one icon.
- A missing method has target `0` and is recorded in `blocked_method`.
- Duplicate stat groups have identical gameplay fields. Their physical copies
  may differ only in display name and flavor text.
- Every physical card has a short reconstruction flavor sentence.

## Encounter groups

| Type | Names and copies |
| --- | --- |
| Locations | Mountain of Darkness, Thorned Pass (2); Eternal Blossom Forest, Spirit's Rest Woods (2); Dragon Crystal Caverns, Night Flower Depths (2); Forest of Whispering Waves; Serpent's Spine; Tengu Peak; Crashing Waves Cave |
| Oni | Oni (2); Oni; Hannya; Kasha (2); Kasha (2); Hannya; Oni |
| Bakemono | Kitsune (2); Tanuki (2); Kamaitachi (2); Tanuki (2); Kamaitachi; Kitsune |
| Tsukumogami | Jatai, Seto Taisho (2); Kasa Obaki, Morinji no Kama, Shogoro (3); Hyotan Kozu, Hahakigami (2); Bakezori; Biwa Bokuboku; Chochin-obake |
| Dragons | Luck Dragon (3); Sea Dragon (3); Rain Dragon (2); Eight-Headed Dragon; Dragon King |

The exact VP, icon, target, reward, and block values live in the JSON source
of truth. The loader validates the 50-card shape, unique IDs, region/icon
constraints, reward legality, and blocked-method representation.
