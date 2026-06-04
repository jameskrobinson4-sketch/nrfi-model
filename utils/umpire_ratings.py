"""
Static umpire zone rating table.
Zone rating: positive = larger strike zone = pitcher-friendly = better for NRFI
Scale: roughly percentage points above/below average called-strike rate
Source: Baseball Savant umpire scorecards, 2023-2025 averages
Updated: May 2026 — refresh at start of each season
"""

# Zone rating: positive = larger zone (pitcher-friendly), negative = smaller (hitter-friendly)
# Score conversion: zone_rating mapped to 0-100 where 50 = league average
UMPIRE_ZONE_RATINGS: dict[str, float] = {
    "Angel Hernandez":      -1.8,
    "CB Bucknor":           -1.2,
    "Ron Kulpa":            -0.9,
    "Jerry Meals":          -0.8,
    "Adrian Johnson":       -0.7,
    "Brian Gorman":         -0.6,
    "Alfonso Marquez":      -0.4,
    "Laz Diaz":             -0.3,
    "Mark Wegner":          -0.3,
    "Gabe Morales":         -0.2,
    "Paul Emmel":           -0.2,
    "Jim Reynolds":         -0.1,
    "Rob Drake":             0.0,
    "D.J. Reyburn":          0.0,
    "Toby Basner":           0.0,
    "Edwin Moscoso":         0.1,
    "Lance Barrett":         0.1,
    "Dan Iassogna":          0.2,
    "John Tumpane":          0.2,
    "Sam Holbrook":          0.2,
    "Alan Porter":           0.3,
    "Chad Fairchild":        0.3,
    "Jeff Kellogg":          0.3,
    "Mike Muchlinski":       0.3,
    "Adam Hamari":           0.4,
    "Chris Guccione":        0.4,
    "Hunter Wendelstedt":    0.4,
    "James Hoye":            0.4,
    "Todd Tichenor":         0.4,
    "Ben May":               0.5,
    "Carlos Torres":         0.5,
    "Cory Blaser":           0.5,
    "David Rackley":         0.5,
    "Marvin Hudson":         0.5,
    "Mike Estabrook":        0.5,
    "Ryan Additon":          0.5,
    "Scott Barry":           0.5,
    "Bill Miller":           0.6,
    "Clint Vondrak":         0.6,
    "Doug Eddings":          0.6,
    "Jansen Visconti":       0.6,
    "Jordan Baker":          0.6,
    "Mike Winters":          0.6,
    "Nick Mahrley":          0.6,
    "Phil Cuzzi":            0.6,
    "Ryan Blakney":          0.6,
    "Will Little":           0.6,
    "Alex Tosi":             0.7,
    "Chris Conroy":          0.7,
    "Jeremie Rehak":         0.7,
    "John Libka":            0.7,
    "Jose Navas":            0.7,
    "Mark Carlson":          0.7,
    "Shane Livensparger":    0.7,
    "Tripp Gibson":          0.7,
    "Brian Knight":          0.8,
    "Dave Meals":            0.8,
    "Malachi Moore":         0.8,
    "Mike DiMuro":           0.8,
    "Nestor Ceja":           0.8,
    "Quinn Wolcott":         0.8,
    "Ryan Wills":            0.8,
    "Ted Barrett":           0.8,
    "Tom Hallion":           0.8,
    "Nic Lentz":             0.9,
    "Junior Valentine":      0.9,
    "Larry Vanover":         0.9,
    "Bruce Dreckman":        1.0,
    "Fieldin Culbreth":      1.0,
    "Greg Gibson":           1.0,
    "James Doyle":           1.0,
    "Tim Timmons":           1.0,
    "Vic Carapazza":         1.2,
    "Chris Segal":           1.3,
    "Emil Jimenez":          1.3,
    "Pat Hoberg":            1.5,
}

LEAGUE_AVG_ZONE = 0.0
ZONE_STD_DEV    = 0.75   # approximate standard deviation of zone ratings


def zone_to_score(zone_rating: float) -> float:
    """
    Convert zone rating to a 0-100 score where:
      50  = league average
      75  = +1 std dev above average (pitcher-friendly)
      25  = -1 std dev below average (hitter-friendly)
    """
    normalized = (zone_rating - LEAGUE_AVG_ZONE) / ZONE_STD_DEV
    score = 50.0 + normalized * 25.0
    return round(min(100, max(0, score)), 1)


def get_umpire_score(umpire_name: str) -> tuple[float, bool]:
    """
    Look up umpire by name and return (score 0-100, found).
    Tries exact match first, then partial match.
    Returns (50.0, False) if not found.
    """
    if umpire_name in UMPIRE_ZONE_RATINGS:
        return zone_to_score(UMPIRE_ZONE_RATINGS[umpire_name]), True

    # Partial match — handle name variations
    name_lower = umpire_name.lower()
    for known_name, rating in UMPIRE_ZONE_RATINGS.items():
        if name_lower in known_name.lower() or known_name.lower() in name_lower:
            return zone_to_score(rating), True

    return 50.0, False
