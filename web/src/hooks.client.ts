import type { HandleClientError } from "@sveltejs/kit";

function describeClientError(error: unknown): Record<string, unknown> {
  if (error instanceof Error) {
    return {
      name: error.name,
      message: error.message,
      stack: error.stack
    };
  }

  return {
    value: error
  };
}

export const handleError: HandleClientError = ({ error, event, message, status }) => {
  console.error("civibus_client_error", {
    error: describeClientError(error),
    message,
    routeId: event.route.id,
    status
  });

  return { message };
};
