from redsailcut.path_order import sort_inside_first, sort_nearest_neighbor


def _square(x: float, y: float, size: float) -> list[tuple[float, float]]:
    """Axis-aligned closed square with its top-left at (x, y)."""
    return [
        (x, y),
        (x + size, y),
        (x + size, y + size),
        (x, y + size),
        (x, y),
    ]


def test_empty_input_returns_empty():
    assert sort_inside_first([]) == []


def test_two_separate_squares_keep_original_order():
    a = _square(0, 0, 10)
    b = _square(20, 0, 10)
    result = sort_inside_first([a, b])
    assert result == [a, b]


def test_small_square_inside_large_square_small_goes_first():
    big = _square(0, 0, 100)
    small = _square(40, 40, 20)
    result = sort_inside_first([big, small])
    assert result == [small, big]


def test_three_level_nesting_innermost_first():
    outer = _square(0, 0, 100)
    middle = _square(20, 20, 60)
    inner = _square(40, 40, 20)
    # Shuffled input
    result = sort_inside_first([outer, inner, middle])
    assert result == [inner, middle, outer]


def test_mix_closed_and_open_closed_first_open_after():
    big = _square(0, 0, 100)
    small = _square(40, 40, 20)
    # Open polyline: start ≠ end
    open_line = [(200.0, 10.0), (210.0, 50.0), (220.0, 10.0)]
    result = sort_inside_first([open_line, big, small])
    # Closed sorted inside-first, then open
    assert result[0] == small
    assert result[1] == big
    assert result[2] == open_line


def test_open_polylines_are_sorted_by_min_y():
    line_low = [(0.0, 30.0), (10.0, 31.0)]
    line_mid = [(0.0, 15.0), (10.0, 16.0)]
    line_high = [(0.0, 5.0), (10.0, 6.0)]
    result = sort_inside_first([line_low, line_mid, line_high])
    # Sorted by ascending min Y (top of SVG first)
    assert result == [line_high, line_mid, line_low]


def test_letter_o_puts_counter_before_outer_ring():
    # Outer circle-ish (approximated as octagon square) + inner hole
    outer = _square(0, 0, 50)
    counter = _square(15, 15, 20)
    result = sort_inside_first([outer, counter])
    assert result[0] == counter
    assert result[1] == outer


def test_overlapping_bboxes_but_not_nested_treated_as_siblings():
    # Two squares whose bboxes overlap partially but neither contains the other
    a = _square(0, 0, 30)   # bbox (0,0,30,30)
    b = _square(20, 20, 30)  # bbox (20,20,50,50)
    # Neither bbox contains the other → both depth 0 → original order preserved
    result = sort_inside_first([a, b])
    assert result == [a, b]


def test_single_closed_and_single_open_order_preserved_within_groups():
    closed = _square(0, 0, 10)
    op = [(100.0, 0.0), (110.0, 5.0)]
    assert sort_inside_first([closed, op]) == [closed, op]
    assert sort_inside_first([op, closed]) == [closed, op]


def test_degenerate_single_point_polyline_treated_as_open():
    single = [(5.0, 5.0)]
    box = _square(0, 0, 10)
    result = sort_inside_first([single, box])
    # box is closed, single is open → closed first, open after
    assert result == [box, single]


def test_sort_is_stable_for_equal_depth_shapes():
    a = _square(0, 0, 10)
    b = _square(20, 0, 10)
    c = _square(40, 0, 10)
    assert sort_inside_first([a, b, c]) == [a, b, c]
    assert sort_inside_first([c, b, a]) == [c, b, a]


def test_nearest_neighbor_reduces_pen_up_travel_order():
    first = [(0.0, 0.0), (10.0, 0.0)]
    far = [(100.0, 0.0), (110.0, 0.0)]
    near = [(12.0, 0.0), (20.0, 0.0)]

    assert sort_nearest_neighbor([first, far, near]) == [first, near, far]


def test_nearest_neighbor_can_start_near_cutter_origin():
    top = [(100.0, 0.0), (110.0, 0.0)]
    bottom = [(5.0, 95.0), (15.0, 95.0)]

    assert sort_nearest_neighbor([top, bottom], start=(0.0, 100.0)) == [
        bottom,
        top,
    ]


def test_nearest_neighbor_preserves_path_direction():
    first = [(0.0, 0.0), (10.0, 0.0)]
    reversed_candidate = [(20.0, 0.0), (11.0, 0.0)]

    assert sort_nearest_neighbor([first, reversed_candidate])[1] == reversed_candidate
