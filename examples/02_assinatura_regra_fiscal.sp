/* Exemplo sintetico - Hotfix Unifier
   Categoria esperada: 2 - ASSINATURA DE PROCEDURES/FUNCTIONS

   Publica apenas a assinatura (corpo vazio) de APLICAR_REGRA_FISCAL.
   Isso precisa existir no banco ANTES de CALC_TOTAL_PEDIDO (arquivo 03),
   que a invoca — senao a criacao da procedure chamadora falha com
   "Procedure APLICAR_REGRA_FISCAL not found".
   O corpo real desta procedure entra em uma hotfix posterior. */

CREATE OR ALTER PROCEDURE APLICAR_REGRA_FISCAL (
    IDPEDIDO BIGINT,
    UF_DESTINO VARCHAR(2))
RETURNS (
    ALIQUOTA NUMERIC(18,4))
AS
BEGIN
  SUSPEND;
END
