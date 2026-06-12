import { Lock } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";

export default function PaperTradingPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Paper Trading" description="Gated behind research validation" />
      <div className="flex flex-col items-center justify-center gap-4 rounded-lg border border-dashed py-20 text-center">
        <Lock className="h-10 w-10 text-muted-foreground" />
        <div>
          <p className="text-sm font-medium">Locked until a strategy earns ADVANCE_TO_PAPER_TRADING</p>
          <p className="mx-auto mt-2 max-w-md text-xs text-muted-foreground">
            By design, this module has no UI, no mock positions, and no order plumbing. It is built
            only after the validation gate — profit factor, Sharpe, drawdown, Monte Carlo,
            walk-forward, and regime tests — passes on a registered experiment.
          </p>
        </div>
      </div>
    </div>
  );
}
