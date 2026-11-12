import { test, expect } from "@playwright/test";

const ADMIN = {
  email: process.env.E2E_ADMIN_EMAIL || "admin@test.com",
  password: process.env.E2E_ADMIN_PASSWORD || "AdminRealE2e!2026",
};
const USER = {
  email: process.env.E2E_USER_EMAIL || "e2e.analyst.user@example.com",
  password: process.env.E2E_USER_PASSWORD || "E2eReview!2026x",
};

async function login(page, email, password) {
  await page.goto("/login");
  await page.getByRole("textbox", { name: "Adresse e-mail" }).fill(email);
  await page.getByRole("textbox", { name: "Mot de passe" }).fill(password);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page).toHaveURL(/\/app\/?$/);
}

async function logout(page) {
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.setItem("pm.loggedOut", "1");
  });
}

test.describe("FE-3 automatisations n8n", () => {
  test("admin automations page is guarded, shows status and the 3 workflows", async ({
    page,
  }) => {
    await login(page, USER.email, USER.password);
    await page.goto("/app/admin/automations");
    await expect(
      page.getByRole("heading", { name: "Accès non autorisé" })
    ).toBeVisible();
    await expect(
      page.getByText("Votre rôle ne permet pas d'ouvrir cette page.")
    ).toBeVisible();

    await logout(page);
    await login(page, ADMIN.email, ADMIN.password);

    await page
      .getByRole("link", { name: "Automatisations n8n" })
      .click();
    await expect(page).toHaveURL(/\/app\/admin\/automations\/?$/);
    await expect(
      page.getByRole("heading", { name: "Automatisations n8n" })
    ).toBeVisible();

    await expect(
      page.getByRole("heading", {
        name: /Intégration active|Intégration désactivée|n8n injoignable/,
      })
    ).toBeVisible();

    await expect(page.getByText("Activation", { exact: true })).toBeVisible();
    await expect(page.getByText("Hôte du webhook")).toBeVisible();
    await expect(page.getByText("Livrés (24 h)")).toBeVisible();
    await expect(page.getByText("Échecs (24 h)")).toBeVisible();

    await expect(
      page.getByRole("button", { name: "Tester l'intégration" })
    ).toBeVisible();
    const n8nLink = page.getByRole("link", { name: "Ouvrir n8n" });
    await expect(n8nLink).toBeVisible();
    await expect(n8nLink).toHaveAttribute("href", /^https?:\/\//);
    await expect(n8nLink).toHaveAttribute("target", "_blank");

    await expect(page.getByText("Événements récents")).toBeVisible();

    await expect(
      page.getByRole("heading", { name: "Workflows attendus dans n8n" })
    ).toBeVisible();
    for (const workflow of [
      "W1 · Alerte phishing confirmé",
      "W2 · Cas à examiner",
      "W3 · Rapport quotidien",
      "W4 · Signalement par formulaire",
    ]) {
      await expect(
        page.getByRole("heading", { name: workflow })
      ).toBeVisible();
    }
    await expect(page.getByText("scan.confirmed", { exact: false }).first()).toBeVisible();
    await expect(
      page.getByText("scan.needs_review", { exact: false }).first()
    ).toBeVisible();
    await expect(
      page.getByText("Planification n8n", { exact: true }).first()
    ).toBeVisible();
    await expect(
      page.getByText("Prévu", { exact: true }).first()
    ).toBeVisible();
    await expect(
      page.getByText("Non activé dans cette version : à venir.", { exact: true })
    ).toBeVisible();
    await expect(
      page.getByText(
        "n8n n'ouvre jamais les liens : toutes les analyses passent par l'API de l'application.",
        { exact: false }
      )
    ).toBeVisible();
  });
});
