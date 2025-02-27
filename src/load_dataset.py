import glob
import numpy as np
import os
import tensorflow as tf
import tqdm


def load_dataset(enc, path, combine):
    paths = []
    if os.path.isfile(path):
        # Simple file
        paths.append(path)
    elif os.path.isdir(path):
        # Directory
        for (dirpath, _, fnames) in os.walk(path):
            for fname in fnames:
                paths.append(os.path.join(dirpath, fname))
    else:
        # Assume glob
        paths = glob.glob(path)

    token_chunks = []
    raw_text = ''
    for path in tqdm.tqdm(paths):
        if path.endswith('.npz'):
            # Pre-encoded
            with np.load(path) as npz:
                for item in npz.files:
                    token_chunks.append(npz[item])
        else:
            # Plain text
            with open(path, 'r') as fp:
                raw_text += fp.read()
            if len(raw_text) >= combine:
                tokens = np.stack(enc.encode(raw_text))
                token_chunks.append(tokens)
                raw_text = ''
            else:
                raw_text += '<|endoftext|>'
    if raw_text:
        tokens = np.stack(enc.encode(raw_text))
        token_chunks.append(tokens)
    return token_chunks


def binary_search(f, lo, hi):
    if f(lo) or not f(hi):
        return None
    while hi > lo + 1:
        mid = (lo + hi) // 2
        if f(mid):
            hi = mid
        else:
            lo = mid
    return hi


def load_qna_dataset(enc,path,length=1024):
    """Question followed by answer. Question may be truncated
    but answer may not. No npz file"""
    paths = []
    if os.path.isfile(path):
        # Simple file
        paths.append(path)
    elif os.path.isdir(path):
        # Directory
        for (dirpath, _, fnames) in os.walk(path):
            for fname in fnames:
                paths.append(os.path.join(dirpath, fname))
    else:
        # Assume glob
        paths = glob.glob(path)

    token_chunks = []
    for path in tqdm.tqdm(paths):
        if path.endswith('.npz'):
            # Pre-encoded
            raise Exception("npz not supported for qna")
        else:
            # Plain text
            
            try:
                with open(path, 'r') as fp:
                    raw_text = fp.read()
                    for qna in tqdm.tqdm(raw_text.split('\n\n')):
                        if qna=='': continue
                        question,answer = qna.split('\n')
                        answer="\n"+answer
                        qchunk = np.stack(enc.encode(question))
                        achunk = np.stack(enc.encode(answer))
                        qchunk = qchunk[:length-len(achunk)]
                        chunk = np.concatenate([qchunk,achunk],axis=0)
                        token_chunks.append(chunk)
            except Exception as e:
                print(str(e))
                import pdb;
                pdb.set_trace()
    return token_chunks


class Sampler(object):
    """Fairly samples a slice from a set of variable sized chunks.

    'Fairly' means that the distribution is the same as sampling from one concatenated chunk,
    but without crossing chunk boundaries."""

    def __init__(self, chunks, seed=None):
        self.chunks = chunks
        self.total_size = sum(chunk.shape[0] for chunk in chunks)
        self.boundaries = [0]
        for i in range(len(chunks)):
            self.boundaries.append(self.boundaries[-1] + chunks[i].shape[0])
        self.rs = np.random.RandomState(seed=seed)

    def sample(self, length):
        assert length < self.total_size // len(
            self.chunks
        ), "Dataset files are too small to sample {} tokens at a time".format(
            length)
        while True:
            index = self.rs.randint(0, self.total_size - length - 1)
            i = binary_search(lambda j: self.boundaries[j] > index, 0,
                              len(self.boundaries) - 1) - 1
            if self.boundaries[i + 1] > index + length:
                within_chunk = index - self.boundaries[i]
                return self.chunks[i][within_chunk:within_chunk + length]

class WholeChunkSampler(object):
    """Returns one complete chunk with right truncation after sampling
    one chunk among all chunks.
    This is useful for some specific tasks like question answering
    where we can't begin from arbitrary position, but only from start.

    If the length of the chunk is smaller than the desired length, next
    chunk is appended."""

    def __init__(self,chunks,seed=None):
        self.chunks = chunks
        self.n_chunks = len(self.chunks)
        self.total_size = sum(chunk.shape[0] for chunk in chunks)
        self.rs = np.random.RandomState(seed=seed)

    def sample(self,length):

        index = self.rs.randint(self.n_chunks)

        chunk = self.chunks[index][:length]

        while len(chunk)<length:
            index = (index+1)%self.n_chunks
            chunk = np.concatenate((chunk,
                            self.chunks[index][:length-len(chunk)]),axis=0)

        return chunk