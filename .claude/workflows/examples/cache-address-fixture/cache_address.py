def split_address(address, size, assoc, line_size):
    # Deliberately broken fixture for the end-to-end repair example.
    sets = size // (assoc * line_size)
    return {'tag': address // line_size, 'index': address % sets, 'offset': 0}
