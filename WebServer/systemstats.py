import gc
import os


def get_memory_stats():
    gc.collect()
    free = gc.mem_free()
    used = gc.mem_alloc()
    return {'used': used, 'free': free, 'total': used + free}


def get_storage_stats():
    block_size, frag_size, total_blocks, free_blocks, avail_blocks = os.statvfs('/')[0:5]
    total = block_size * total_blocks
    free = block_size * avail_blocks
    return {'used': total - free, 'free': free, 'total': total}


def free_percent(stats):
    if stats['total'] <= 0:
        return 100.0
    return (stats['free'] / stats['total']) * 100.0


def format_bytes(n):
    if n >= 1024 * 1024:
        return "{:.1f} MB".format(n / (1024 * 1024))
    if n >= 1024:
        return "{:.1f} KB".format(n / 1024)
    return "{} B".format(n)
