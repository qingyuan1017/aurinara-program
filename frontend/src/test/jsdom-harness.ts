// Shared jsdom harness for component tests of the workbench shared components.
//
// jsdom implements the DOM API but not the layout engine, so libraries that
// measure elements (React Flow) or read pointer geometry (dnd-kit) break
// without a few shims. This module installs:
//
//   * `ResizeObserver`              — React Flow / dnd-kit observe node size.
//   * element-dimension getters     — `getBoundingClientRect`, `offsetWidth`,
//                                      `offsetHeight` return a fixed non-zero
//                                      box so measured layouts are stable.
//   * pointer-capture + PointerEvent — dnd-kit's PointerSensor calls
//                                      `setPointerCapture`/`releasePointerCapture`
//                                      and constructs `PointerEvent`s, neither of
//                                      which jsdom provides.
//   * `DataTransfer`                 — native HTML5 file-drop tests build a
//                                      `dataTransfer` payload.
//
// Call `installJsdomHarness()` once per test file (typically in `beforeAll`).
// It is idempotent, so repeated calls are harmless.

const DEFAULT_RECT = {
  x: 0,
  y: 0,
  top: 0,
  left: 0,
  bottom: 200,
  right: 200,
  width: 200,
  height: 200,
  toJSON() {
    return this
  },
} as const

let installed = false

/** Install all jsdom shims the shared components need. Idempotent. */
export function installJsdomHarness(): void {
  if (installed) return
  installed = true

  installResizeObserver()
  installElementDimensions()
  installPointerShims()
  installDataTransfer()
}

function installResizeObserver(): void {
  if (typeof globalThis.ResizeObserver !== 'undefined') return
  class ResizeObserverMock implements ResizeObserver {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  globalThis.ResizeObserver =
    ResizeObserverMock as unknown as typeof ResizeObserver
}

function installElementDimensions(): void {
  if (typeof Element === 'undefined') return

  // A stable non-zero bounding box so React Flow's node measurement and
  // dnd-kit's collision math have something to work with.
  Element.prototype.getBoundingClientRect = function getBoundingClientRect() {
    return { ...DEFAULT_RECT } as DOMRect
  }

  defineReadonlyNumber(HTMLElement.prototype, 'offsetWidth', DEFAULT_RECT.width)
  defineReadonlyNumber(HTMLElement.prototype, 'offsetHeight', DEFAULT_RECT.height)

  if (typeof globalThis.DOMRect === 'undefined') {
    globalThis.DOMRect = class DOMRectMock {
      x: number
      y: number
      width: number
      height: number
      constructor(x = 0, y = 0, width = 0, height = 0) {
        this.x = x
        this.y = y
        this.width = width
        this.height = height
      }
      get top() {
        return this.y
      }
      get left() {
        return this.x
      }
      get right() {
        return this.x + this.width
      }
      get bottom() {
        return this.y + this.height
      }
      toJSON() {
        return this
      }
      static fromRect(rect?: DOMRectInit): DOMRect {
        return new DOMRectMock(
          rect?.x,
          rect?.y,
          rect?.width,
          rect?.height,
        ) as unknown as DOMRect
      }
    } as unknown as typeof DOMRect
  }
}

function defineReadonlyNumber(
  target: object,
  prop: string,
  value: number,
): void {
  const existing = Object.getOwnPropertyDescriptor(target, prop)
  if (existing && existing.get) return
  Object.defineProperty(target, prop, {
    configurable: true,
    get() {
      return value
    },
  })
}

function installPointerShims(): void {
  if (typeof Element === 'undefined') return

  if (!Element.prototype.setPointerCapture) {
    Element.prototype.setPointerCapture = function setPointerCapture() {}
  }
  if (!Element.prototype.releasePointerCapture) {
    Element.prototype.releasePointerCapture = function releasePointerCapture() {}
  }
  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = function hasPointerCapture() {
      return false
    }
  }

  // jsdom has no PointerEvent; dnd-kit's PointerSensor dispatches/reads them.
  if (typeof globalThis.PointerEvent === 'undefined') {
    class PointerEventMock extends MouseEvent {
      pointerId: number
      pointerType: string
      isPrimary: boolean
      constructor(type: string, params: PointerEventInit = {}) {
        super(type, params)
        this.pointerId = params.pointerId ?? 1
        this.pointerType = params.pointerType ?? 'mouse'
        this.isPrimary = params.isPrimary ?? true
      }
    }
    globalThis.PointerEvent =
      PointerEventMock as unknown as typeof PointerEvent
  }
}

function installDataTransfer(): void {
  if (typeof globalThis.DataTransfer !== 'undefined') return
  class DataTransferMock {
    dropEffect = 'none'
    effectAllowed = 'all'
    private _files: File[] = []
    get files(): FileList {
      const list = this._files
      return {
        ...list,
        length: list.length,
        item: (i: number) => list[i] ?? null,
        [Symbol.iterator]: () => list[Symbol.iterator](),
      } as unknown as FileList
    }
    items = {
      add: (file: File) => {
        this._files.push(file)
      },
    }
    setData() {}
    getData() {
      return ''
    }
  }
  globalThis.DataTransfer =
    DataTransferMock as unknown as typeof DataTransfer
}
