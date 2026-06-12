import { ExperimentDetailView } from "./view";

export default async function ExperimentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ExperimentDetailView runId={id} />;
}
