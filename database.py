import mysql.connector

def get_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="Mm@12345",
        database="stock_analysis_db"
    )