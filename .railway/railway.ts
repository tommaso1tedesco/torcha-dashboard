import { defineRailway, github, postgres, project, service, volume } from "railway/iac";

export default defineRailway(() => {
  const Postgres = postgres("Postgres", { region: "iad" });
  Postgres.networking = { privateNetworkEndpoint: "postgres" };
  const postgresVolume = volume("postgres-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "iad", sizeMB: 500 });

  const web = service("web", {
    source: github("tommaso1tedesco/torcha-dashboard", { branch: "main" }),
    start: "streamlit run app.py --server.port $PORT --server.address 0.0.0.0",
    env: {
      DATABASE_URL: Postgres.env.DATABASE_URL,
      ACTIVE_CATEGORIES: "attualita,tecnologia",
      DASHBOARD_WINDOW_HOURS: "24",
      APIFY_TOKEN: "",
    },
  });

  const worker = service("worker", {
    source: github("tommaso1tedesco/torcha-dashboard", { branch: "main" }),
    start: "python3 worker.py",
    env: {
      DATABASE_URL: Postgres.env.DATABASE_URL,
      ACTIVE_CATEGORIES: "attualita,tecnologia",
      APIFY_TOKEN: "",
    },
  });

  return project("torcha-dashboard", {
    resources: [Postgres, postgresVolume, web, worker],
  });
});
