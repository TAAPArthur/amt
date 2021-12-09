import functools
import logging

from PIL import Image
from heapq import heappop, heappush
from threading import Lock

CACHE_SIZE = 60000

MAX_INDIVIDUAL_COST = 30
MAX_AVG_COST = 10


def avg(L):
    return sum(L) / len(L)


@functools.lru_cache(maxsize=CACHE_SIZE)
def compute_diff(A, B):
    if isinstance(A, int):
        return abs(A - B)
    return ((A[0] - B[0])**2 + (A[1] - B[1])**2 + (A[2] - B[2])**2)**.5


class Cell:
    def __init__(self, pixels, x, y, w, h, index):
        self.pixels = pixels
        self.x, self.y, self.w, self.h = x, y, w, h
        self.index = index

    @functools.lru_cache(maxsize=CACHE_SIZE)
    def get_vert_diff(self, start_x, start_y, offset):
        c = 0
        num = (offset // 2 + offset % 2) * (self.h // 2 + self.h % 2)
        for index in range(0, offset, 2):
            s = 0
            for n in range(0, self.h, 2):
                s += compute_diff(self.pixels[self.x + self.w - offset + index, self.y + n], self.pixels[start_x + index, start_y + n])
            c += s / num
            if c > MAX_INDIVIDUAL_COST:
                return c
        return c

    @functools.lru_cache(maxsize=CACHE_SIZE)
    def get_hor_diff(self, start_x, start_y, offset):
        return avg([compute_diff(self.pixels[self.x + n, self.y + self.h - offset + index], self.pixels[start_x + n, start_y + index]) for n in range(0, self.w, 2) for index in range(0, offset, 2)])


@functools.lru_cache(maxsize=CACHE_SIZE)
def find_neighbors(cells, right, bottom, offset, branch_factor=4):
    results = []
    for cell in cells:
        cost_x = cell.get_vert_diff(right[0], right[1], offset[0])
        if cost_x <= MAX_INDIVIDUAL_COST:
            cost_y = cell.get_hor_diff(bottom[0], bottom[1], offset[1])
            cost = cost_x + cost_y
            if cost <= MAX_INDIVIDUAL_COST:
                results.append((cell, cost))

    results.sort(key=lambda x: x[1])

    for result in results[:branch_factor]:
        yield result


class State:
    def __init__(self, grid, remaining_cells, row=0, col=0, max_cost=0):
        self.grid, self.remaining_cells = grid, remaining_cells
        self.col, self.row = col, row
        self.max_cost = max_cost

    def __lt__(self, other):
        return len(self.remaining_cells) - len(other.remaining_cells)


def find_solution(cells, num_rows, num_cols, offset, max_iters=None, branch_factor=None):
    heap = []
    cells = tuple(cells)
    W, H = cells[0].w, cells[0].h
    assert cells
    assert len(cells) > 1
    heappush(heap, (0, State([[]], cells, 0)))
    i = 0
    min_cells = len(cells)
    if not branch_factor:
        branch_factor = 4
    while heap:
        i += 1
        cost, state = heappop(heap)
        min_cells = min(min_cells, len(state.remaining_cells))
        if not state.remaining_cells:
            state.grid.pop()
            logging.debug("Found solution iterations %d Max cost %f", i, state.max_cost)

            return state.grid
        if len(state.remaining_cells) - min_cells > num_cols * 2:
            logging.debug("Skipping old entry; iter %s", i)
            continue

        if max_iters and i >= max_iters:
            logging.debug("Surpassed the max about of iterations")
            break

        if state.col == 0:
            RIGHT_EDGE = num_cols * W, (num_rows - 1 - state.row) * H + offset[1] * (state.row + 1)
        else:
            RIGHT_EDGE = state.grid[-1][-1].x, state.grid[-1][-1].y
        if state.row:
            BOTTOM_EDGE = (state.grid[-2][state.col].x, state.grid[-2][state.col].y)
        else:
            BOTTOM_EDGE = ((num_cols - 1 - state.col) * W + offset[0] * (state.col + 1), num_rows * H)

        results = find_neighbors(state.remaining_cells, RIGHT_EDGE, BOTTOM_EDGE, offset=offset, branch_factor=branch_factor)

        depth = len(cells) - len(state.remaining_cells) + 1
        assert depth
        assert results
        for result in results:
            cell = result[0]
            new_cost = result[1] + cost
            grid = list(state.grid)
            grid[-1] = grid[-1] + [cell]
            remaining_cells = tuple((c for c in state.remaining_cells if c != cell))
            new_row, new_col = state.row, state.col + 1
            if new_col == num_cols:
                new_col, new_row = 0, new_row + 1
                grid.append([])
                assert len(grid) > 1
            newState = State(grid, remaining_cells, new_row, new_col, max(state.max_cost, result[1]))
            heappush(heap, (new_cost, newState))
    return False


def paste(ref: Image.Image, img: Image.Image, orig_box, ref_box, offset_x=0, offset_y=0):
    ref.paste(img.crop(
        (orig_box[0], orig_box[1], orig_box[0] + orig_box[2], orig_box[1] + orig_box[3])),
        (ref_box[0] - offset_x, ref_box[1] - offset_y, ref_box[0] + ref_box[2] - offset_x, ref_box[1] + ref_box[3] - offset_y))


class GenericDecoder:

    _lock = Lock()
    _cache = {}
    _pending_cache = {}

    # How many times we have to detect a solution before it is cached
    # 0 disables, 1 always adds a solution to cache
    PENDING_CACHE_NUM = 3

    @staticmethod
    def load_cells(pixels, num_rows, num_cols, W, H):
        cells = []
        i = 0
        for y in range(num_rows):
            for x in range(num_cols):
                cells.append(Cell(pixels, W * x, y * H, W, H, i))
                i += 1
        return cells

    @staticmethod
    def descramble(cells, num_rows, num_cols, offset, max_iters=None, branch_factor=None):
        sorted_cells = find_solution(cells, num_rows, num_cols, offset, max_iters=max_iters, branch_factor=branch_factor)
        if sorted_cells is False:
            return False
        for row in sorted_cells:
            row.reverse()
        sorted_cells.reverse()
        return sorted_cells

    @staticmethod
    def cells_to_int_matrix(sorted_cells):
        grid = []
        for row in sorted_cells:
            grid.append(tuple((cell.index for cell in row if cell)))
        grid = tuple(grid)
        return grid

    @staticmethod
    def solve_image(img: Image, W=201, H=192, key=None, max_iters=None, branch_factor=None) -> Image.Image:
        super_key = (key, img.size)
        if key and super_key in GenericDecoder._cache:
            logging.debug("Using cache; super_key %s", super_key)
            grid, W, H = GenericDecoder._cache[super_key]
            solution, _ = GenericDecoder.solve_image_helper(img, W, H, grid=grid)
            return solution

        for w in range(W - 16, W + 17, 8):
            for h in range(H - 16, H + 17, 8):
                solution, sorted_cells = GenericDecoder.solve_image_helper(img, w, h, max_iters=max_iters, branch_factor=branch_factor)
                if solution:
                    if key:
                        grid = GenericDecoder.cells_to_int_matrix(sorted_cells)

                        GenericDecoder._pending_cache[super_key, grid] = GenericDecoder._pending_cache.get((super_key, grid), 0) + 1
                        if GenericDecoder._pending_cache[super_key, grid] == GenericDecoder.PENDING_CACHE_NUM:
                            GenericDecoder._cache[super_key] = grid, w, h
                    return solution
        return None

    @staticmethod
    def solve_image_helper(img: Image, W, H, grid=None, max_iters=None, branch_factor=None, offset=(16, 16)) -> Image.Image:
        img_width, img_height = img.size
        num_cols = int((img_width) / W)
        num_rows = int((img_height) / H)
        if img_width - num_cols * W <= offset[0] or img_height - num_rows * H <= offset[1]:
            return None, None
        pixels = img.load()

        cells = GenericDecoder.load_cells(pixels, num_rows, num_cols, W, H)
        assert cells
        sorted_cells = []
        if grid:
            sorted_cells = []
            for y in range(num_rows):
                sorted_cells.append([])
                for x in range(num_cols):
                    sorted_cells[-1].append(cells[grid[y][x]])
        else:
            sorted_cells = GenericDecoder.descramble(cells, num_rows, num_cols, offset, max_iters=max_iters, branch_factor=branch_factor)
            if sorted_cells is False:
                return None, None

        new_img_size = img_width - offset[0] * num_cols, img_height - offset[1] * num_rows
        ref = Image.new(img.mode, new_img_size)

        offset_x, offset_y = offset[0] * num_cols, offset[1] * num_rows
        paste(ref, img, (num_cols * W, img_height - num_rows * H, img_width - num_cols * W, num_rows * H), (
            (num_cols * W, img_height - num_rows * H, img_width - num_cols * W, num_rows * H)
        ), offset_x=offset_x, offset_y=offset_y)
        paste(ref, img, (0, num_rows * H, img_width, img_height - num_rows * H), (
            (0, num_rows * H, img_width, img_height - num_rows * H)
        ), offset_x=offset_x, offset_y=offset_y)

        for y in range(num_rows):
            row = sorted_cells[y]
            for x in range(num_cols):
                if row[x]:
                    paste(ref, img, (row[x].x, row[x].y, W, H), (x * W, y * H, W, H), x * offset[0], y * offset[1])

        return ref, sorted_cells

    @staticmethod
    def descramble_and_save_img(data, path, key=None, max_iters=None, branch_factor=None):
        orig = Image.open(data)
        with GenericDecoder._lock:
            solution = GenericDecoder.solve_image(orig, key=key, max_iters=max_iters, branch_factor=None)
            if solution and path:
                solution.save(path)
            return bool(solution)
