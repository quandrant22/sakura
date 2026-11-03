// jsdom без ResizeObserver: доске (react-grid-layout), панелям чата и виджетам он нужен для размеров.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;
