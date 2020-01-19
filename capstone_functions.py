import requests
import numpy as np
import pandas as pd
import math

import folium
from folium.features import DivIcon

CLIENT_ID = 'VXYAGD1UCDJXEPUG3JUKI24MZMLYQUOPMYMEDB0MBXZQFMU3'
CLIENT_SECRET = '1QR1DGV15DE0QEZM5VVYSDFQ1TZJMSP1G4TYVP2ITYYLMWMF'
VERSION = '20180605'
LIMIT = 100

SE = np.array([43.804226, -111.757579])
SW = np.array([43.804226, -111.807453])
NW = np.array([43.840199, -111.807453])
NE = np.array([43.840199, -111.757579])
CORNERS = np.array([SE, SW, NW, NE])

MAP_CENTER = (round(np.mean([lat for lat, long in CORNERS]), 6),
              round(np.mean([long for lat, long in CORNERS]), 6))


def calc_grid_radius(grid_size, side_length=4_000):
    # Calculate radius in meters to cover grid section diagonals and round to
    # the next highest 10 meters
    return math.ceil((((((side_length / grid_size)**2)*2)**0.5)/2)/10)*10

def build_category_tree(tree, level=0, parent=None, categories=[]):
    # Build a dictionary of Foursquare categories by recursing the hierarchy in
    # the categories API JSON file
    if not tree:
        return categories
    else:
        for category in tree:
            categories.append({
                'category': category['name'],
                'level': level,
                'parent': parent
            })
            build_category_tree(category['categories'], level=level+1,
                               parent=category['name'], categories=categories)
        return categories


def add_category_change(new_category, venue_names: list, d):
    # Add a "category: list of venues to update" pair to a dictionary, and
    # return a new dictionary.
    d[new_category] = venue_names
    return d


def map_category_group(category, max_depth=0):
    # Search the category hierarchy for the parent group with a hierarchy level
    # at least as low as max_depth. The ultimate parent level is 0.
    current_depth = categories[categories['category'] == category
                              ]['level'].values[0]
    current_group = categories[categories['category'] == category
                              ]['category'].values[0]

    while current_depth > max_depth:
        current_depth -= 1
        current_group = categories[categories['category'] == current_group
                                  ]['parent'].values[0]

    return current_group




def calc_grid_centers(grid_size: int, corners: np.array=CORNERS) -> np.array:
    # Generate an array containing the center coordinates for each grid section
    num_segments = grid_size * 2
    vert_segment_len = abs(corners[0][0] - corners[3][0]) / num_segments
    horiz_segment_len = abs(corners[2][1] - corners[3][1]) / num_segments

    centers = []

    for v in range(1, num_segments, 2):
        v_coord = v_coord = corners[-1][0] - v * vert_segment_len
        for h in range(1, num_segments, 2):
            centers.append((v_coord, corners[1][1] + h * horiz_segment_len))

    return np.array(centers)


def grid_square_bounds(grid_size: int, corners: np.array=CORNERS) -> np.array:
    # Generate an array containing the rectangle corner bounds for each grid
    # section
    vert_segment_len = abs(corners[0][0] - corners[3][0]) / grid_size
    horiz_segment_len = abs(corners[2][1] - corners[3][1]) / grid_size

    polygons = np.zeros((grid_size, grid_size, 2, 2))

    northing_start = corners[2][0]
    easting_start = corners[2][1]

    for v in range(grid_size):
        for h in range(grid_size):
            # Define NW & SE corner coodinates
            polygons[v, h, 0] = [northing_start - vert_segment_len*v,
                                 easting_start + horiz_segment_len*h]
            polygons[v, h, 1] = [northing_start - (vert_segment_len * (v + 1)),
                                 easting_start + (horiz_segment_len * (h + 1))]

    return polygons


def draw_rexburg_map(corners=CORNERS, zoom_start=13, border=True,
                     grid=True, grid_size=1, grid_numbers=False,
                     circles=False, grid_radius=None):

    rexburg_map = folium.Map(location=MAP_CENTER, zoom_start=zoom_start)

    if grid_radius is None:
        grid_radius = calc_grid_radius(grid_size)

    if grid_numbers or grid:
        grid_squares = grid_square_bounds(grid_size)

    if grid_numbers or circles:
        grid_centers = calc_grid_centers(grid_size)

    if border:
        folium.Rectangle(
            [each for each in corners[::2]], color='gray', weight=2
            ).add_to(rexburg_map)

    if grid:
        for row in grid_squares:
            for square in row:
                folium.Rectangle(
                    square,
                    fill=False,
                    weight=0.5,
                    color='gray'
                    ).add_to(rexburg_map)

    if grid_numbers:
        counter = 1
        for row in grid_squares:
            for square in row:
                folium.map.Marker(
                    [grid_centers[counter-1][0],
                     grid_centers[counter-1][1]],
                    icon=DivIcon(icon_size=(1,1),
                                 icon_anchor=(5,5),
                                 html=f'<div style="text-align:center;font-size:6pt"'
                                      f'>{counter}</div>')
                    ).add_to(rexburg_map)

                counter += 1

    if circles:
        for lat, long in grid_centers:
            folium.Circle(
                [lat, long],
                radius=grid_radius,
                fill=True,
                fill_opacity=0.2,
                weight=0.3
                ).add_to(rexburg_map)

    return rexburg_map


def venue_grid_section(lat, long, grid_size, square_bounds=None):
    # Inefficiently determines which grid section a given point is in. Returns
    # None if point is outside the grid.
    if square_bounds is None:
        square_bounds = grid_square_bounds(grid_size)

    for number, coords in enumerate(square_bounds.reshape(-1, 2, 2)):
        lat_max, long_min, lat_min, long_max = coords.flatten()
        if lat_min <= lat <= lat_max and long_min <= long <= long_max:
            return int(number + 1)
    return None



def get_nearby_venues(grid_size):
    # Retrieve venues from the Foursquare API for all sections of a grid within
    # a given radius of a list of grid sections and their cooresponding
    # coordinates. Return a pd.DataFrame

    grid_sections = range(1, grid_size**2 + 1)
    coords = calc_grid_centers(grid_size)
    latitudes = coords[:, 0]
    longitudes = coords[:, 1]
    radius = calc_grid_radius(grid_size)

    venues_list=[]
    print('Getting grid sections: ', end='')
    for grid_section, lat, lng in zip(grid_sections, latitudes, longitudes):
        print(grid_section, end=' ')

        # create the API request URL
        req_params = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'll': f'{lat},{lng}',
            'v': VERSION,
            'radius': radius,
            'limit': LIMIT
        }
        url = 'https://api.foursquare.com/v2/venues/search'

        # make the GET request
        results = requests.get(url, req_params).json(
                    )['response']['venues']

        # return only relevant information for each nearby venue
        for v in results:
            try:
                category = v['categories'][0]['name']
            except IndexError:
                category = 'None'

            venues_list.append({
                'grid_section': grid_section,
                'grid_section_lat': lat,
                'grid_section_long': lng,
                'venue': v['name'],
                'v_lat': v['location']['lat'],
                'v_long': v['location']['lng'],
                'category': category
            })

    nearby_venues = pd.DataFrame(venues_list)

    return(nearby_venues)


# Populate the categories DataFrame from the Foursquare API
req_params = {
    'client_id': CLIENT_ID,
    'client_secret': CLIENT_SECRET,
    'v': VERSION
    }

url = 'https://api.foursquare.com/v2/venues/categories'

category_tree = requests.get(url, req_params).json()

categories = pd.DataFrame(build_category_tree(category_tree['response']['categories']))
