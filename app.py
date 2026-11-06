from flask import Flask, render_template, request, redirect, url_for, flash
from database import get_connection
import pandas as pd
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import io
import base64

app = Flask(__name__)
app.secret_key = "stockwise-local-secret-key"


# ---------------- CURRENT STOCK HELPER ----------------

def get_current_stock(cursor, product_id, opening_stock):

    cursor.execute("""
        SELECT COALESCE(
            SUM(
                CASE
                    WHEN transaction_type = 'IN' THEN quantity
                    WHEN transaction_type = 'OUT' THEN -quantity
                    ELSE 0
                END
            ), 0
        ) AS movement
        FROM stock_transactions
        WHERE product_id = %s
    """, (product_id,))

    movement = cursor.fetchone()["movement"] or 0

    cursor.execute("""
        SELECT COALESCE(
            SUM(
                CASE
                    WHEN adjustment_type = 'INCREASE' THEN quantity
                    WHEN adjustment_type = 'DECREASE' THEN -quantity
                    ELSE 0
                END
            ), 0
        ) AS adjustment_movement
        FROM stock_adjustments
        WHERE product_id = %s
    """, (product_id,))

    adjustment_movement = (
        cursor.fetchone()["adjustment_movement"] or 0
    )

    return (
        int(opening_stock or 0)
        + int(movement)
        + int(adjustment_movement)
    )


# ---------------- DASHBOARD ----------------

@app.route("/")
def index():

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT
                p.product_id,
                p.sku,
                p.product_name,
                p.category_id,
                p.opening_stock,
                p.reorder_level,
                p.unit_cost,
                c.category_name
            FROM products p
            LEFT JOIN categories c
                ON p.category_id = c.category_id
            ORDER BY p.product_id DESC
        """)

        products = cursor.fetchall()

        for product in products:

            current_stock = get_current_stock(
                cursor,
                product["product_id"],
                product["opening_stock"]
            )

            product["current_stock"] = current_stock

            product["stock_value"] = (
                current_stock * float(product["unit_cost"] or 0)
            )

            product["low_stock"] = (
                current_stock <= int(product["reorder_level"] or 0)
            )

            product["status"] = (
                "Low Stock" if product["low_stock"] else "In Stock"
            )

        total_products = len(products)

        total_stock = sum(
            p["current_stock"] for p in products
        )

        inventory_value = sum(
            p["stock_value"] for p in products
        )

        low_stock_products = [
            p for p in products if p["low_stock"]
        ]

        low_stock_count = len(low_stock_products)

        in_stock_count = sum(
            1 for p in products if not p["low_stock"]
        )

        stock_chart_labels = [
            p["product_name"] for p in products
        ]

        stock_chart_values = [
            p["current_stock"] for p in products
        ]

        value_chart_values = [
            round(p["stock_value"], 2) for p in products
        ]

        stock_status_values = [
            in_stock_count,
            low_stock_count
        ]

        return render_template(
            "index.html",
            products=products,
            total_products=total_products,
            total_stock=total_stock,
            inventory_value=inventory_value,
            total_inventory_value=inventory_value,
            low_stock_products=low_stock_products,
            low_stock_count=low_stock_count,
            low_stock=low_stock_products,
            in_stock_count=in_stock_count,
            stock_chart_labels=stock_chart_labels,
            stock_chart_values=stock_chart_values,
            value_chart_values=value_chart_values,
            stock_status_values=stock_status_values
        )

    finally:
        cursor.close()
        conn.close()


# ---------------- ADD PRODUCT ----------------

@app.route("/add-product", methods=["GET", "POST"])
def add_product():

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:

        if request.method == "POST":

            sku = request.form.get("sku", "").strip()
            product_name = request.form.get("product_name", "").strip()
            category_value = request.form.get("category_id", "").strip()
            opening_value = request.form.get("opening_stock", "").strip()
            reorder_value = request.form.get("reorder_level", "").strip()
            cost_value = request.form.get("unit_cost", "").strip()

            try:

                opening_stock = int(opening_value)
                reorder_level = int(reorder_value)
                unit_cost = float(cost_value)
                category_id = int(category_value)

                if not sku or not product_name:

                    flash(
                        "Please enter the SKU and product name.",
                        "error"
                    )

                elif (
                    opening_stock < 0
                    or reorder_level < 0
                    or unit_cost < 0
                ):

                    flash("Values cannot be negative.", "error")

                else:

                    cursor.execute("""
                        INSERT INTO products
                        (
                            sku,
                            product_name,
                            category_id,
                            opening_stock,
                            reorder_level,
                            unit_cost
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        sku,
                        product_name,
                        category_id,
                        opening_stock,
                        reorder_level,
                        unit_cost
                    ))

                    conn.commit()

                    flash(
                        "Product added successfully!",
                        "success"
                    )

                    return redirect(url_for("index"))

            except ValueError:

                flash(
                    "Please enter valid numbers in all required fields.",
                    "error"
                )

        cursor.execute("""
            SELECT category_id, category_name
            FROM categories
            ORDER BY category_name
        """)

        categories = cursor.fetchall()

        return render_template(
            "add_product.html",
            categories=categories
        )

    finally:
        cursor.close()
        conn.close()


# ---------------- EDIT PRODUCT ----------------

@app.route("/edit-product/<int:product_id>", methods=["GET", "POST"])
def edit_product(product_id):

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT *
            FROM products
            WHERE product_id = %s
        """, (product_id,))

        product = cursor.fetchone()

        if not product:
            flash("Product not found.", "error")
            return redirect(url_for("index"))

        if request.method == "POST":

            sku = request.form.get("sku", "").strip()
            product_name = request.form.get("product_name", "").strip()

            try:

                category_id = int(request.form.get("category_id", ""))
                opening_stock = int(request.form.get("opening_stock", ""))
                reorder_level = int(request.form.get("reorder_level", ""))
                unit_cost = float(request.form.get("unit_cost", ""))

                if not sku or not product_name:

                    flash("SKU and product name are required.", "error")

                elif min(opening_stock, reorder_level, unit_cost) < 0:

                    flash("Values cannot be negative.", "error")

                else:

                    cursor.execute("""
                        UPDATE products
                        SET sku = %s,
                            product_name = %s,
                            category_id = %s,
                            opening_stock = %s,
                            reorder_level = %s,
                            unit_cost = %s
                        WHERE product_id = %s
                    """, (
                        sku,
                        product_name,
                        category_id,
                        opening_stock,
                        reorder_level,
                        unit_cost,
                        product_id
                    ))

                    conn.commit()

                    flash("Product updated successfully!", "success")

                    return redirect(url_for("index"))

            except ValueError:

                flash("Please enter valid values.", "error")

        cursor.execute("""
            SELECT category_id, category_name
            FROM categories
            ORDER BY category_name
        """)

        categories = cursor.fetchall()

        return render_template(
            "edit_product.html",
            product=product,
            categories=categories
        )

    finally:
        cursor.close()
        conn.close()
        # ---------------- DELETE PRODUCT ----------------

@app.route("/delete-product/<int:product_id>", methods=["POST"])
def delete_product(product_id):

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT product_id
            FROM products
            WHERE product_id = %s
        """, (product_id,))

        product = cursor.fetchone()

        if not product:

            flash("Product not found.", "error")

        else:

            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM stock_transactions
                WHERE product_id = %s
            """, (product_id,))

            transaction_history = cursor.fetchone()["total"]

            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM stock_adjustments
                WHERE product_id = %s
            """, (product_id,))

            adjustment_history = cursor.fetchone()["total"]

            if transaction_history > 0 or adjustment_history > 0:

                flash(
                    "This product has stock history and cannot be deleted.",
                    "error"
                )

            else:

                cursor.execute("""
                    DELETE FROM products
                    WHERE product_id = %s
                """, (product_id,))

                conn.commit()

                flash("Product deleted successfully!", "success")

    except Exception:

        conn.rollback()

        flash(
            "Product could not be deleted. It may be linked to other records.",
            "error"
        )

    finally:

        cursor.close()
        conn.close()

    return redirect(url_for("index"))


# ---------------- STOCK ADJUSTMENTS ----------------

@app.route("/adjustments", methods=["GET", "POST"])
def adjustments():

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:

        if request.method == "POST":

            try:

                product_id = int(request.form.get("product_id", ""))
                quantity = int(request.form.get("quantity", ""))
                adjustment_type = request.form.get("adjustment_type", "")
                reason = request.form.get("reason", "").strip()

                if quantity <= 0:

                    flash(
                        "Quantity must be greater than zero.",
                        "error"
                    )

                elif adjustment_type not in ("INCREASE", "DECREASE"):

                    flash(
                        "Select a valid adjustment type.",
                        "error"
                    )

                elif not reason:

                    flash(
                        "Please enter the adjustment reason.",
                        "error"
                    )

                else:

                    cursor.execute("""
                        SELECT product_id, opening_stock
                        FROM products
                        WHERE product_id = %s
                        FOR UPDATE
                    """, (product_id,))

                    product = cursor.fetchone()

                    if not product:

                        flash("Product not found.", "error")

                    else:

                        current_stock = get_current_stock(
                            cursor,
                            product_id,
                            product["opening_stock"]
                        )

                        if (
                            adjustment_type == "DECREASE"
                            and quantity > current_stock
                        ):

                            flash(
                                f"Insufficient stock! Available: {current_stock}",
                                "error"
                            )

                        else:

                            # Save stock adjustment
                            cursor.execute("""
                                INSERT INTO stock_adjustments
                                (
                                    product_id,
                                    adjustment_type,
                                    quantity,
                                    reason
                                )
                                VALUES (%s, %s, %s, %s)
                            """, (
                                product_id,
                                adjustment_type,
                                quantity,
                                reason
                            ))

                            # Save audit log
                            cursor.execute("""
                                INSERT INTO stock_audit_log
                                (
                                    product_id,
                                    action_type,
                                    quantity_changed,
                                    remarks
                                )
                                VALUES (%s, %s, %s, %s)
                            """, (
                                product_id,
                                "STOCK_ADJUSTMENT_" + adjustment_type,
                                quantity,
                                reason
                            ))

                            conn.commit()

                            flash(
                                "Stock adjustment saved successfully!",
                                "success"
                            )

                            return redirect(url_for("adjustments"))

            except ValueError:

                conn.rollback()

                flash(
                    "Enter valid product and quantity values.",
                    "error"
                )

        cursor.execute("""
            SELECT
                product_id,
                sku,
                product_name,
                opening_stock
            FROM products
            ORDER BY product_name
        """)

        products = cursor.fetchall()

        for product in products:

            product["current_stock"] = get_current_stock(
                cursor,
                product["product_id"],
                product["opening_stock"]
            )

        cursor.execute("""
            SELECT
                a.adjustment_id,
                a.adjustment_date,
                a.adjustment_type,
                a.quantity,
                a.reason,
                p.product_name,
                p.sku
            FROM stock_adjustments a
            JOIN products p
                ON p.product_id = a.product_id
            ORDER BY a.adjustment_id DESC
        """)

        adjustment_history = cursor.fetchall()

        return render_template(
            "adjustments.html",
            products=products,
            adjustment_history=adjustment_history
        )

    except Exception:

        conn.rollback()
        raise

    finally:

        cursor.close()
        conn.close()


# ---------------- STOCK TRANSACTIONS ----------------

@app.route("/transactions", methods=["GET", "POST"])
def transactions():

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:

        if request.method == "POST":

            try:

                product_id = int(
                    request.form.get("product_id", "")
                )

                quantity = int(
                    request.form.get("quantity", "")
                )

                transaction_type = request.form.get(
                    "transaction_type", ""
                )

                supplier_text = request.form.get(
                    "supplier_id", ""
                ).strip()

                supplier_id = (
                    int(supplier_text) if supplier_text else None
                )

                notes = request.form.get("notes", "").strip()

                if quantity <= 0:

                    flash(
                        "Quantity must be greater than zero.",
                        "error"
                    )

                elif transaction_type not in ("IN", "OUT"):

                    flash(
                        "Please select Stock IN or Stock OUT.",
                        "error"
                    )

                else:

                    cursor.execute("""
                        SELECT product_id, opening_stock
                        FROM products
                        WHERE product_id = %s
                        FOR UPDATE
                    """, (product_id,))

                    product = cursor.fetchone()

                    if not product:

                        flash(
                            "Selected product was not found.",
                            "error"
                        )

                    else:

                        current_stock = get_current_stock(
                            cursor,
                            product["product_id"],
                            product["opening_stock"]
                        )

                        if (
                            transaction_type == "OUT"
                            and quantity > current_stock
                        ):

                            flash(
                                f"Insufficient stock! Available stock: {current_stock}",
                                "error"
                            )

                        else:

                            # Save stock transaction
                            cursor.execute("""
                                INSERT INTO stock_transactions
                                (
                                    product_id,
                                    supplier_id,
                                    transaction_date,
                                    transaction_type,
                                    quantity,
                                    notes
                                )
                                VALUES (
                                    %s, %s, CURRENT_DATE, %s, %s, %s
                                )
                            """, (
                                product_id,
                                supplier_id,
                                transaction_type,
                                quantity,
                                notes
                            ))

                            # Save audit log
                            cursor.execute("""
                                INSERT INTO stock_audit_log
                                (
                                    product_id,
                                    action_type,
                                    quantity_changed,
                                    remarks
                                )
                                VALUES (%s, %s, %s, %s)
                            """, (
                                product_id,
                                "STOCK_" + transaction_type,
                                quantity,
                                notes or "Stock transaction recorded"
                            ))

                            conn.commit()

                            flash(
                                "Stock transaction saved successfully!",
                                "success"
                            )

                            return redirect(url_for("transactions"))

            except ValueError:

                conn.rollback()

                flash(
                    "Please select a product and enter a valid quantity.",
                    "error"
                )

        cursor.execute("""
            SELECT
                product_id,
                sku,
                product_name,
                opening_stock
            FROM products
            ORDER BY product_name
        """)

        products = cursor.fetchall()

        for product in products:

            product["current_stock"] = get_current_stock(
                cursor,
                product["product_id"],
                product["opening_stock"]
            )

        cursor.execute("""
            SELECT supplier_id, supplier_name
            FROM suppliers
            ORDER BY supplier_name
        """)

        suppliers = cursor.fetchall()

        cursor.execute("""
            SELECT
                st.transaction_id,
                st.transaction_date,
                st.transaction_type,
                st.quantity,
                st.notes,
                p.product_name,
                p.sku,
                s.supplier_name
            FROM stock_transactions st
            JOIN products p
                ON p.product_id = st.product_id
            LEFT JOIN suppliers s
                ON s.supplier_id = st.supplier_id
            ORDER BY st.transaction_id DESC
            LIMIT 100
        """)

        transaction_history = cursor.fetchall()

        return render_template(
            "transactions.html",
            products=products,
            suppliers=suppliers,
            transactions=transaction_history,
            transaction_history=transaction_history
        )

    finally:

        cursor.close()
        conn.close()
        # ---------------- PRODUCT MOVEMENT ANALYSIS ----------------

@app.route("/analysis")
def analysis():

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT
                p.product_id,
                p.product_name,
                p.sku,
                st.transaction_type,
                st.quantity,
                st.transaction_date
            FROM products p
            LEFT JOIN stock_transactions st
                ON p.product_id = st.product_id
            ORDER BY p.product_name
        """)

        records = cursor.fetchall()

        columns = [
            "product_id",
            "product_name",
            "sku",
            "transaction_type",
            "quantity",
            "transaction_date"
        ]

        df = pd.DataFrame(records, columns=columns)

        if df.empty:

            movement_data = []
            fast_products = []
            slow_products = []

        else:

            df["quantity"] = pd.to_numeric(
                df["quantity"],
                errors="coerce"
            ).fillna(0)

            df["stock_in"] = df["quantity"].where(
                df["transaction_type"] == "IN", 0
            )

            df["stock_out"] = df["quantity"].where(
                df["transaction_type"] == "OUT", 0
            )

            summary = df.groupby(
                ["product_id", "product_name", "sku"],
                as_index=False
            ).agg(
                total_in=("stock_in", "sum"),
                total_out=("stock_out", "sum")
            )

            summary["net_movement"] = (
                summary["total_in"] - summary["total_out"]
            )

            summary = summary.sort_values(
                "total_out",
                ascending=False
            )

            movement_data = summary.to_dict("records")

            fast_products = summary[
                summary["total_out"] > 0
            ].head(5).to_dict("records")

            slow_products = summary[
                summary["total_out"] == 0
            ].to_dict("records")

        # -------- MATPLOTLIB STOCK MOVEMENT CHART --------

        chart_image = None

        if movement_data:

            names = [
                item["product_name"]
                for item in movement_data
            ]

            stock_in = [
                item["total_in"]
                for item in movement_data
            ]

            stock_out = [
                item["total_out"]
                for item in movement_data
            ]

            plt.figure(figsize=(10, 5))

            x = range(len(names))
            width = 0.35

            plt.bar(
                [i - width / 2 for i in x],
                stock_in,
                width,
                label="Stock IN"
            )

            plt.bar(
                [i + width / 2 for i in x],
                stock_out,
                width,
                label="Stock OUT"
            )

            plt.xlabel("Products")
            plt.ylabel("Quantity")
            plt.title("Stock Movement Analysis")

            plt.xticks(
                list(x),
                names,
                rotation=45,
                ha="right"
            )

            plt.legend()
            plt.tight_layout()

            image_buffer = io.BytesIO()

            plt.savefig(
                image_buffer,
                format="png",
                bbox_inches="tight"
            )

            image_buffer.seek(0)

            chart_image = base64.b64encode(
                image_buffer.getvalue()
            ).decode("utf-8")

            plt.close()

        return render_template(
            "analysis.html",
            movement_data=movement_data,
            fast_products=fast_products,
            slow_products=slow_products,
            chart_image=chart_image
        )

    finally:

        cursor.close()
        conn.close()


# ---------------- APPLICATION START ----------------

if __name__ == "__main__":

    app.run(debug=True)