/**
 * Лёгкий трекер активной вкладки (без ре-рендеров) для умного показа push-уведомлений.
 */

let activeTabRoute = 'index';

export function setActiveTabRoute(name: string): void {
  if (name) {
    activeTabRoute = name;
  }
}

export function getActiveTabRoute(): string {
  return activeTabRoute;
}
