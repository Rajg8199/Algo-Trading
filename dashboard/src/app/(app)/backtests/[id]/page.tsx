import { BacktestDetailView } from "./view";

export default async function BacktestPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <BacktestDetailView runId={id} />;
}
