import { createRoot } from "react-dom/client"
import BlocRedimensionnable from "@/components/chat/BlocRedimensionnable"
import { SimpleTable } from "@/components/blocks/tables/SimpleTable"

// Un tableau de 40 lignes : plus haut que son plafond (min(70vh, 560px)), il défile
// — c'est le cas exact des tableaux du chat que Noa n'arrivait pas à agrandir.
const lignes = Array.from({ length: 40 }, (_, i) => [`Poste ${i + 1}`, String((i + 1) * 3), "m²", `${(i + 1) * 7},00 €`])

createRoot(document.getElementById("app")!).render(
  <div id="colonne" style={{ maxWidth: 900, width: "100%", padding: 12, boxSizing: "border-box", ["--bloc-largeur" as any]: "620px" }}>
    <div className="sym-in">
      <BlocRedimensionnable>
        <SimpleTable titre="Quantitatif — essai" columns={["Poste", "Quantité", "Unité", "P.U. HT"]} rows={lignes} />
      </BlocRedimensionnable>
    </div>
  </div>
)
