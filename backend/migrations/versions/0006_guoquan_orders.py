"""锅圈订单表。数据由启动或首次查询时从 CSV 导入，不写进迁移。

revision: 0006_guoquan_orders
down_revision: 0005_asset_owner
"""
from alembic import op

revision = "0006_guoquan_orders"
down_revision = "0005_asset_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS `guoquan_orders` (
          `order_no`              VARCHAR(32)  NOT NULL,
          `order_create_time`     DATETIME     NULL,
          `pay_time`               DATETIME     NULL,
          `order_status`           VARCHAR(16)  NULL,
          `order_type`             VARCHAR(16)  NULL,
          `order_channel`          VARCHAR(16)  NULL,
          `activity_id`            VARCHAR(32)  NULL,
          `activity_name`          VARCHAR(128) NULL,
          `store_id`               VARCHAR(16)  NULL,
          `store_name`             VARCHAR(64)  NULL,
          `store_address`          VARCHAR(255) NULL,
          `store_business_hours`   VARCHAR(32)  NULL,
          `store_phone`            VARCHAR(32)  NULL,
          `fulfillment_type`       VARCHAR(16)  NULL,
          `goods_list`             TEXT         NULL,
          `goods_quantity`         INT          NULL,
          `goods_amount`           DECIMAL(12,2) NULL,
          `delivery_fee`           DECIMAL(12,2) NULL,
          `packing_fee`            DECIMAL(12,2) NULL,
          `total_amount`           DECIMAL(12,2) NULL,
          `discount_amount`        DECIMAL(12,2) NULL,
          `pay_amount`             DECIMAL(12,2) NULL,
          `points_earned`          INT          NULL,
          `is_coupon_used`         VARCHAR(8)   NULL,
          `coupon_code`            VARCHAR(32)  NULL,
          `coupon_type`            VARCHAR(16)  NULL,
          `coupon_name`            VARCHAR(128) NULL,
          `coupon_value`           DECIMAL(12,2) NULL,
          `receiver_name`          VARCHAR(64)  NULL,
          `receiver_phone`         VARCHAR(20)  NULL,
          `address_id`             VARCHAR(32)  NULL,
          `address`                VARCHAR(255) NULL,
          `order_remark`           VARCHAR(255) NULL,
          `order_complete_time`    DATETIME     NULL,
          `refund_amount`          DECIMAL(12,2) NULL,
          `user_id`                VARCHAR(16)  NULL,
          `user_nickname`          VARCHAR(64)  NULL,
          `user_name`              VARCHAR(64)  NULL,
          `user_gender`            VARCHAR(8)   NULL,
          `member_level`           VARCHAR(16)  NULL,
          `member_points`          INT          NULL,
          `user_phone`             VARCHAR(20)  NULL,
          `need_invoice`           VARCHAR(8)   NULL,
          PRIMARY KEY (`order_no`),
          KEY `idx_orders_time` (`order_create_time`),
          KEY `idx_orders_store` (`store_name`),
          KEY `idx_orders_status` (`order_status`),
          KEY `idx_orders_channel` (`order_channel`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS `guoquan_orders`")
