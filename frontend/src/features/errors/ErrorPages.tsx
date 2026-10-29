import { Button } from "../../components/ui/primitives";
import { Lock } from "../../components/icons";
import { useRouter } from "../../lib/router";

export function NotFound() {
  const { navigate } = useRouter();
  return (
    <div className="max-w-lg py-10">
      <p className="text-sm font-medium text-muted">404</p>
      <h1 className="mt-1 text-xl font-semibold">This page does not exist</h1>
      <p className="mt-2 text-sm text-muted">The link may be old or mistyped. Go back to the hub to find what you need.</p>
      <Button className="mt-4" variant="primary" onClick={() => navigate("/")}>
        Go to the hub
      </Button>
    </div>
  );
}

export function Forbidden({ area }: { area: string }) {
  const { navigate } = useRouter();
  return (
    <div className="max-w-lg py-10" data-testid="forbidden">
      <Lock aria-hidden className="size-6 text-muted" />
      <p className="mt-3 text-sm font-medium text-muted">403</p>
      <h1 className="mt-1 text-xl font-semibold">{area} is not available to your role</h1>
      <p className="mt-2 text-sm text-muted">
        Access is set by your administrator. If you need it for your work, ask them to add the right role to your account.
      </p>
      <Button className="mt-4" onClick={() => navigate("/")}>
        Back to the hub
      </Button>
    </div>
  );
}
