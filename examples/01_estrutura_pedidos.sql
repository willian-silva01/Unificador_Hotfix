/* Exemplo sintetico - Hotfix Unifier
   Categoria esperada: 1 - TABELAS (estrutura)
   Adiciona o campo de desconto negociado no cabecalho do pedido. */

ALTER TABLE PEDIDOS ADD DESCONTO_NEGOCIADO NUMERIC(18,2) DEFAULT 0;

ALTER TABLE PEDIDOS ADD OBSERVACAO_INTERNA VARCHAR(255);

CREATE INDEX IDX_PEDIDOS_DATA_STATUS ON PEDIDOS (DATA_EMISSAO, STATUS);
