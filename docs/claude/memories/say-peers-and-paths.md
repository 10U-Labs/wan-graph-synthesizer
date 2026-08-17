# Say peers and paths

Two words carry almost every question about a backbone: the peers a site is joined to, and the paths between them. A peer is another backbone site this one has a circuit to. A path is one way from one site to another, and it crosses whatever cities the fiber makes it cross — `Ashburn, VA -> Martinsburg, WV -> Pittsburgh, PA -> ... -> Minot, ND` is one path over nine cities. Answer in those two words, in chat as much as in issues, and the reader can follow without opening anything.

Do not say "cable". Cable is a real thing at one scale only: a single span between two adjacent points, which is a `PhysicalEdge` in `synthesizer.input_graph` and an entry of the published `edges` collection. A path rides many of them, so "Ashburn has four cables" says nothing a reader can act on — four spans, four paths, or four circuits are three different numbers and only one of them is what was meant. The same goes for "link" used loosely: an entry of the published `backbone-links` collection is one path between two sites, and its `path` field is the list of cities it crosses.

Do not say "route" either, even though it means the right thing. It is the harm a synonym does rather than the harm a wrong word does: a reader met with path in one paragraph and route in the next has to stop and work out whether the same thing is meant, and on a page that also says span, circuit and link they will not be sure they got it right. Say path every time. The identifiers keep the spelling they have and are written exactly as they are spelled — `synthesizer.ceiling.routes_per_peer`, `synthesizer.ceiling.independent_routes`, `backbone.diverse_mesh_routes`, `backbone.restore_diverse_paths` — because a name the reader can open is worth more than a consistent page, and renaming them would be a code change made for the sake of prose. The prose around them says path. Much of the docstring and issue text already on disk says route, written before this was settled; match this rule rather than the paragraph next to you, and leave the old text alone unless the file is being changed for some other reason.

Peers and diverse paths are different things, and keeping them apart is not pedantry — conflating them is the defect in GitHub issue #59. `number_of_diverse_paths` in a tenant's `etc/*.yml` is how many ways out of a site the operator is buying. `synthesizer.backbone.select_backbone_mesh_pairs` spends that number as peer slots: each site reaches for that many peers. How many paths one pair of sites is then drawn with is a separate question, answered by `synthesizer.ceiling.routes_per_peer`, and the answer is one unless there are too few peers to reach. A site's diverse paths are the links out of it that no single city's loss takes two of, which is what `synthesizer.validation.routed_independent_degree` counts — so two peers reached over one shared transit city are one diverse path, and two paths to the same peer over city-disjoint fiber are two.

Which word for which thing, when precision is needed:

| thing | word |
| --- | --- |
| one fiber segment between two adjacent points | span, or its type `PhysicalEdge` |
| one way from one backbone site to another | path — never route |
| what an operator orders and pays for monthly | circuit |
| two sites joined by at least one path | a pair |
| the site at the other end of a pair | peer |
| a city every route out of a site crosses | chokepoint, or cut city |
| a place on the map | site, or city — never node |

This was written on 2026-08-17, after a question about Minuteman's Ashburn, VA — why a site asking for two diverse paths had four — was answered twice in the wrong words. The first answer counted cables, which meant nothing on paths crossing nine cities each. The second used peer and diverse path as though they were one thing, which hid the actual defect: Ashburn held three peers and four paths, because one pair was drawn twice. The ban on "route" was added the same day, after a third answer about that same site said route where it had been saying path and had to be asked again. Naming the two separately is what made the defect visible, and `backbone.restore_diverse_paths` — a second circuit between two sites, bought only where the fiber leaves one of them no other way out — is a rule that cannot even be stated without both words.

The telecom vocabulary this sits inside — path diversity rather than mesh degree, site rather than node — is in [how-issues-are-written](how-issues-are-written.md), which requires it of issues; this note requires the same words everywhere else. Naming the function, file and config key rather than describing them is [write-the-exact-name](write-the-exact-name.md).
