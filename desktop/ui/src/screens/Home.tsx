import { Chat } from "../components/Chat";
import { DevicesCard } from "../components/DevicesCard";
import { Mascot, QuickActions, SakuraCard, StatusCard } from "../components/RightColumn";
import { ScenarioBuilder } from "../components/ScenarioBuilder";

// Главная: чат (центр), устройства и конструктор (середина), Sakura/действия/статус (справа).
export function Home({ goDevices, goScenarios }: { goDevices(): void; goScenarios(): void }) {
  return (
    <div className="grid min-h-0 flex-1 gap-4"
         style={{ gridTemplateColumns: "minmax(340px,1fr) clamp(260px,24vw,360px) clamp(240px,21vw,320px)" }}>
      <div className="min-h-0"><Chat /></div>
      <div className="flex min-h-0 flex-col gap-4 overflow-y-auto pr-1">
        <DevicesCard onAll={goDevices} />
        <ScenarioBuilder onOpen={goScenarios} />
      </div>
      <div className="flex min-h-0 flex-col gap-4 overflow-y-auto pr-1">
        <SakuraCard />
        <QuickActions />
        <StatusCard />
        <Mascot />
      </div>
    </div>
  );
}
