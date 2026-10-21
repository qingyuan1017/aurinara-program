import { createSHA256 } from "hash-wasm";

self.onmessage = async (event: MessageEvent<File>) => {
  const file = event.data;
  const hash = await createSHA256();
  const chunkSize = 4 * 1024 * 1024;
  hash.init();
  for (let offset = 0; offset < file.size; offset += chunkSize) {
    hash.update(
      new Uint8Array(
        await file.slice(offset, offset + chunkSize).arrayBuffer(),
      ),
    );
    self.postMessage({
      type: "progress",
      loaded: Math.min(offset + chunkSize, file.size),
      total: file.size,
    });
  }
  self.postMessage({ type: "complete", sha256: hash.digest("hex") });
};
